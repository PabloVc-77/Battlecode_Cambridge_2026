from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav

_ALL_DIRS = (
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
)

_CARDINAL_DIRS = (
    Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
)

_CONVEYOR_TYPES = (
    EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER, EntityType.BRIDGE,
)


def _is_in_bounds(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def _opposite_dir(d: Direction) -> Direction:
    return d.opposite()


class SabotajeSentinel:
    """
    Estrategia de sabotaje contra sentinels enemigos:
    
    1. Localizar el sentinel enemigo más cercano.
    2. Identificar el conveyor que le suministra munición.
    3. Ir al conveyor, destruirlo (fire en propia casilla).
    4. Construir un GUNNER apuntando al sentinel.
    5. Si no hay conveyor visible, buscar casilla adyacente
       al sentinel donde se pueda poner un gunner.
    6. Tras destruir el sentinel, construir camino de conveyors
       hacia nuestra base para robar el recurso del harvester.
    """

    # ── Estados de la máquina de estados ──
    STATE_SEARCH       = 0  # Buscando sentinel enemigo
    STATE_GOTO_FEED    = 1  # Ir al conveyor que alimenta al sentinel
    STATE_DESTROY_FEED = 2  # Destruir el conveyor (fire en my_pos)
    STATE_BUILD_GUNNER = 3  # Construir gunner apuntando al sentinel
    STATE_GOTO_ADJ     = 4  # Ir a casilla adyacente al sentinel (fallback)
    STATE_DESTROY_ADJ  = 5  # Destruir edificio adyacente si lo hay
    STATE_FEED_GUNNER  = 6  # Construir conveyors para alimentar al gunner (evitando sentinel)
    STATE_BUILD_PATH   = 7  # Construir camino de conveyors a casa (robar recurso)
    STATE_DONE         = 8  # Tarea completada, buscar nuevo objetivo

    def __init__(self, c: Controller):
        self.navegador = bugnav.BugNav()

        self.state = self.STATE_SEARCH

        # IDs y posiciones del objetivo
        self.sentinel_id: int | None = None
        self.sentinel_pos: Position | None = None
        self.sentinel_dir: Direction | None = None

        # Conveyor que alimenta al sentinel
        self.feed_conveyor_id: int | None = None
        self.feed_conveyor_pos: Position | None = None

        # Posición donde construir el gunner (puede ser la del conveyor o adyacente)
        self.gunner_build_pos: Position | None = None
        self.gunner_dir: Direction | None = None  # dirección del gunner (hacia el sentinel)

        # Para construir camino a casa
        self.my_core_pos: Position | None = None
        self.harvester_pos: Position | None = None  # harvester del enemigo cercano al sentinel
        self.path_positions: list[Position] = []  # posiciones donde construir conveyors
        self.path_index: int = 0

        # Para alimentar el gunner
        self.feed_chain: list[tuple[Position, Direction]] = []  # (pos, dir) de cada conveyor
        self.feed_chain_index: int = 0
        self.danger_zone: set = set()  # casillas en rango de ataque del sentinel

    # ─────────────────────────────────────────────
    #  LOOP PRINCIPAL
    # ─────────────────────────────────────────────
    def run(self, c: Controller):
        # Inicializar core propio si no lo tenemos
        if self.my_core_pos is None:
            self._find_my_core(c)

        # Verificar que el sentinel sigue vivo
        if self.sentinel_id is not None:
            if not self._entity_alive(c, self.sentinel_id):
                # Sentinel destruido → pasar a construir camino o buscar nuevo
                if self.state in (self.STATE_BUILD_GUNNER, self.STATE_BUILD_PATH):
                    self.state = self.STATE_BUILD_PATH
                else:
                    self._reset_target()

        # Máquina de estados
        if self.state == self.STATE_SEARCH:
            self._do_search(c)
        elif self.state == self.STATE_GOTO_FEED:
            self._do_goto_feed(c)
        elif self.state == self.STATE_DESTROY_FEED:
            self._do_destroy_feed(c)
        elif self.state == self.STATE_BUILD_GUNNER:
            self._do_build_gunner(c)
        elif self.state == self.STATE_GOTO_ADJ:
            self._do_goto_adj(c)
        elif self.state == self.STATE_DESTROY_ADJ:
            self._do_destroy_adj(c)
        elif self.state == self.STATE_FEED_GUNNER:
            self._do_feed_gunner(c)
        elif self.state == self.STATE_BUILD_PATH:
            self._do_build_path_home(c)
        elif self.state == self.STATE_DONE:
            self._reset_target()
            self._do_search(c)

    # ─────────────────────────────────────────────
    #  ESTADOS
    # ─────────────────────────────────────────────

    def _do_search(self, c: Controller):
        """Buscar el sentinel enemigo más cercano."""
        my_pos = c.get_position()
        c.draw_indicator_dot(my_pos, 255, 0, 0)  # rojo = buscando

        self.sentinel_id = self._find_closest_enemy_sentinel(c)
        if self.sentinel_id is None:
            # No hay sentinel visible, explorar
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            next_pos = my_pos.add(move_dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(move_dir):
                c.move(move_dir)
            return

        self.sentinel_pos = c.get_position(self.sentinel_id)
        self.sentinel_dir = c.get_direction(self.sentinel_id)

        # Intentar encontrar el conveyor que alimenta al sentinel
        feed = self._find_feeding_conveyor(c)
        if feed is not None:
            self.feed_conveyor_id, self.feed_conveyor_pos = feed
            self.gunner_build_pos = self.feed_conveyor_pos
            self.gunner_dir = self.feed_conveyor_pos.direction_to(self.sentinel_pos)
            self.state = self.STATE_GOTO_FEED
            c.draw_indicator_line(my_pos, self.feed_conveyor_pos, 0, 255, 0)
        else:
            # Fallback: buscar casilla adyacente donde poner gunner
            adj = self._find_adjacent_gunner_pos(c)
            if adj is not None:
                self.gunner_build_pos, self.gunner_dir = adj
                self.state = self.STATE_GOTO_ADJ
                c.draw_indicator_line(my_pos, self.gunner_build_pos, 0, 0, 255)
            else:
                # No podemos hacer nada con este sentinel, resetear
                self._reset_target()

    def _do_goto_feed(self, c: Controller):
        """Navegar hacia el conveyor que alimenta al sentinel."""
        my_pos = c.get_position()
        target = self.feed_conveyor_pos

        c.draw_indicator_dot(my_pos, 0, 255, 0)  # verde = yendo al conveyor
        c.draw_indicator_line(my_pos, target, 0, 255, 0)

        if my_pos == target:
            # Estamos encima del conveyor, pasar a destruirlo
            self.state = self.STATE_DESTROY_FEED
            return

        # Verificar que el conveyor sigue ahí
        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if bid is None:
                # El conveyor ya no existe, la posición está libre
                self.state = self.STATE_BUILD_GUNNER
                return

        self._navigate_to(c, target)

    def _do_destroy_feed(self, c: Controller):
        """Destruir el conveyor enemigo debajo nuestro con fire(my_pos)."""
        my_pos = c.get_position()
        c.draw_indicator_dot(my_pos, 255, 165, 0)  # naranja = destruyendo

        bid = c.get_tile_building_id(my_pos)
        if bid is None:
            # Conveyor destruido, construir gunner
            self.state = self.STATE_BUILD_GUNNER
            return

        # Si es aliado (ya lo pusimos nosotros), destruir gratis
        if c.get_team(bid) == c.get_team():
            if c.can_destroy(my_pos):
                c.destroy(my_pos)
            self.state = self.STATE_BUILD_GUNNER
            return

        # Atacar el edificio enemigo en nuestra casilla
        if c.get_action_cooldown() == 0 and c.can_fire(my_pos):
            c.fire(my_pos)

    def _do_build_gunner(self, c: Controller):
        """Construir un gunner en la posición del conveyor destruido, apuntando al sentinel."""
        my_pos = c.get_position()
        target = self.gunner_build_pos
        c.draw_indicator_dot(my_pos, 0, 255, 255)  # cyan = construyendo gunner

        # Verificar que todavía sabemos donde está el sentinel
        if self.sentinel_id is not None and self._entity_alive(c, self.sentinel_id):
            self.sentinel_pos = c.get_position(self.sentinel_id)
            self.gunner_dir = target.direction_to(self.sentinel_pos)

        # Necesitamos NO estar encima de la casilla para construir un gunner
        # (gunner no es walkable, así que no se puede construir si hay bot encima)
        if my_pos == target:
            # Moverse a casilla adyacente
            for d in _ALL_DIRS:
                if c.can_move(d):
                    c.move(d)
                    return
            return

        # Verificar que no hay edificio en la casilla
        bid = c.get_tile_building_id(target)
        if bid is not None:
            if c.get_team(bid) == c.get_team():
                # Si ya hay un gunner aliado, éxito
                if c.get_entity_type(bid) == EntityType.GUNNER:
                    self.state = self.STATE_BUILD_PATH
                    return
                # Si hay otro edificio aliado, destruirlo
                if c.can_destroy(target):
                    c.destroy(target)
                return
            else:
                # Aún hay edificio enemigo, volver a destruirlo
                if my_pos.distance_squared(target) <= 0:
                    self.state = self.STATE_DESTROY_FEED
                else:
                    self.state = self.STATE_GOTO_FEED
                return

        # Verificar que la posición está en action radius (r²=2)
        if my_pos.distance_squared(target) > 2:
            self._navigate_to(c, target)
            return

        # Verificar con can_fire_from que el gunner podrá disparar al sentinel
        if self.sentinel_pos is not None and self.gunner_dir is not None:
            can_hit = c.can_fire_from(
                target, self.gunner_dir, EntityType.GUNNER, self.sentinel_pos
            )
            if not can_hit:
                # Probar otras direcciones
                best_dir = self._find_best_gunner_direction(c, target)
                if best_dir is not None:
                    self.gunner_dir = best_dir
                else:
                    # No se puede disparar desde aquí, buscar otra posición
                    adj = self._find_adjacent_gunner_pos(c)
                    if adj is not None:
                        self.gunner_build_pos, self.gunner_dir = adj
                        self.state = self.STATE_GOTO_ADJ
                    else:
                        self._reset_target()
                    return

        # Construir el gunner
        if c.can_build_gunner(target, self.gunner_dir):
            c.build_gunner(target, self.gunner_dir)
            # Calcular zona de peligro y cadena de alimentación
            self._compute_danger_zone(c)
            self._compute_feed_chain(c)
            self.state = self.STATE_FEED_GUNNER
        elif c.get_action_cooldown() > 0:
            pass  # Esperar cooldown
        else:
            # Intentar con cualquier dirección que apunte al sentinel
            best_dir = self._find_best_gunner_direction(c, target)
            if best_dir and c.can_build_gunner(target, best_dir):
                c.build_gunner(target, best_dir)
                self.gunner_dir = best_dir
                self._compute_danger_zone(c)
                self._compute_feed_chain(c)
                self.state = self.STATE_FEED_GUNNER

    def _do_goto_adj(self, c: Controller):
        """Navegar hacia casilla adyacente al sentinel (fallback sin conveyor)."""
        my_pos = c.get_position()
        target = self.gunner_build_pos
        c.draw_indicator_dot(my_pos, 0, 0, 255)  # azul = yendo a adyacente
        c.draw_indicator_line(my_pos, target, 0, 0, 255)

        if my_pos == target:
            # Llegamos, verificar si hay edificio para destruir
            bid = c.get_tile_building_id(my_pos)
            if bid is not None and c.get_team(bid) != c.get_team():
                self.state = self.STATE_DESTROY_ADJ
            else:
                self.state = self.STATE_BUILD_GUNNER
            return

        # Verificar que la posición sigue siendo válida
        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if bid is not None and c.get_team(bid) != c.get_team():
                etype = c.get_entity_type(bid)
                if etype not in _CONVEYOR_TYPES and etype != EntityType.ROAD:
                    # No es caminable, no podemos llegar
                    adj = self._find_adjacent_gunner_pos(c)
                    if adj is not None:
                        self.gunner_build_pos, self.gunner_dir = adj
                    else:
                        self._reset_target()
                    return

        self._navigate_to(c, target)

    def _do_destroy_adj(self, c: Controller):
        """Destruir edificio enemigo en casilla adyacente al sentinel."""
        my_pos = c.get_position()
        c.draw_indicator_dot(my_pos, 255, 100, 0)

        bid = c.get_tile_building_id(my_pos)
        if bid is None:
            self.state = self.STATE_BUILD_GUNNER
            return

        if c.get_team(bid) == c.get_team():
            if c.can_destroy(my_pos):
                c.destroy(my_pos)
            self.state = self.STATE_BUILD_GUNNER
            return

        if c.get_action_cooldown() == 0 and c.can_fire(my_pos):
            c.fire(my_pos)

    def _do_feed_gunner(self, c: Controller):
        """
        Construir cadena de conveyors para alimentar al gunner con titanium,
        evitando las casillas en el rango de ataque del sentinel.
        """
        my_pos = c.get_position()
        c.draw_indicator_dot(my_pos, 255, 255, 0)  # amarillo = alimentando gunner

        # Si no hay cadena calculada o está vacía, saltar a build_path
        if not self.feed_chain:
            self.state = self.STATE_BUILD_PATH
            return

        if self.feed_chain_index >= len(self.feed_chain):
            # Cadena completa, pasar a construir camino a casa
            self.state = self.STATE_BUILD_PATH
            return

        target_pos, conv_dir = self.feed_chain[self.feed_chain_index]

        # Dibujar indicador
        c.draw_indicator_line(my_pos, target_pos, 255, 255, 0)

        # Verificar si ya hay un conveyor aliado en esa posición
        if c.is_in_vision(target_pos):
            bid = c.get_tile_building_id(target_pos)
            if bid is not None and c.get_team(bid) == c.get_team():
                etype = c.get_entity_type(bid)
                if etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                    self.feed_chain_index += 1
                    return

        # Navegar si estamos lejos
        dist = my_pos.distance_squared(target_pos)
        if dist > 2:
            self._navigate_to(c, target_pos)
            return

        # Construir el conveyor
        if c.can_build_conveyor(target_pos, conv_dir):
            c.build_conveyor(target_pos, conv_dir)
            self.feed_chain_index += 1
        elif c.get_action_cooldown() > 0:
            pass  # Esperar cooldown

    def _do_build_path_home(self, c: Controller):
        """
        Construir cadena de conveyors desde la posición del sentinel destruido
        hacia nuestra base para capturar el recurso del harvester enemigo.
        """
        my_pos = c.get_position()
        c.draw_indicator_dot(my_pos, 128, 0, 255)  # púrpura = construyendo camino

        if self.my_core_pos is None:
            self._find_my_core(c)
            if self.my_core_pos is None:
                self.state = self.STATE_DONE
                return

        # Si no hemos calculado el camino aún, hacerlo
        if not self.path_positions:
            start = self.gunner_build_pos if self.gunner_build_pos else my_pos
            self.path_positions = self._compute_conveyor_path(c, start)
            self.path_index = 0

        if self.path_index >= len(self.path_positions):
            self.state = self.STATE_DONE
            return

        target_pos = self.path_positions[self.path_index]

        # La dirección del conveyor debe apuntar HACIA nuestra base
        if self.path_index + 1 < len(self.path_positions):
            next_pos = self.path_positions[self.path_index + 1]
            conv_dir = target_pos.direction_to(next_pos)
        else:
            conv_dir = target_pos.direction_to(self.my_core_pos)

        # Verificar si ya hay un conveyor ahí
        if c.is_in_vision(target_pos):
            bid = c.get_tile_building_id(target_pos)
            if bid is not None:
                if c.get_team(bid) == c.get_team():
                    etype = c.get_entity_type(bid)
                    if etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                        self.path_index += 1
                        return

        # Navegar al lugar y construir
        dist = my_pos.distance_squared(target_pos)
        if dist > 2:
            self._navigate_to(c, target_pos)
            return

        if c.can_build_conveyor(target_pos, conv_dir):
            c.build_conveyor(target_pos, conv_dir)
            self.path_index += 1
        elif c.get_action_cooldown() > 0:
            pass  # Esperar cooldown

    # ─────────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────────

    def _reset_target(self):
        """Limpia todo y vuelve a buscar."""
        self.state = self.STATE_SEARCH
        self.sentinel_id = None
        self.sentinel_pos = None
        self.sentinel_dir = None
        self.feed_conveyor_id = None
        self.feed_conveyor_pos = None
        self.gunner_build_pos = None
        self.gunner_dir = None
        self.harvester_pos = None
        self.path_positions = []
        self.path_index = 0
        self.feed_chain = []
        self.feed_chain_index = 0
        self.danger_zone = set()

    def _find_my_core(self, c: Controller):
        for bid in c.get_nearby_buildings():
            if (c.get_entity_type(bid) == EntityType.CORE
                    and c.get_team(bid) == c.get_team()):
                self.my_core_pos = c.get_position(bid)
                break

    def _entity_alive(self, c: Controller, eid: int) -> bool:
        try:
            c.get_position(eid)
            return True
        except Exception:
            return False

    def _find_closest_enemy_sentinel(self, c: Controller) -> int | None:
        """Devuelve el ID del sentinel enemigo más cercano visible."""
        my_pos = c.get_position()
        my_team = c.get_team()
        best_id = None
        best_d = 10**9

        for eid in c.get_nearby_entities():
            try:
                if c.get_entity_type(eid) != EntityType.SENTINEL:
                    continue
                if c.get_team(eid) == my_team:
                    continue
                d = my_pos.distance_squared(c.get_position(eid))
                if d < best_d:
                    best_d = d
                    best_id = eid
            except Exception:
                continue
        return best_id

    def _find_feeding_conveyor(self, c: Controller) -> tuple[int, Position] | None:
        """
        Busca el conveyor/splitter/bridge que alimenta al sentinel.
        
        Regla: la munición llega al sentinel desde cualquier dirección
        EXCEPTO la dirección en la que apunta el sentinel.
        
        Buscamos en las 4 casillas adyacentes (cardinales) al sentinel
        un conveyor cuya salida apunte HACIA el sentinel.
        """
        if self.sentinel_pos is None or self.sentinel_dir is None:
            return None

        sentinel_pos = self.sentinel_pos
        sentinel_dir = self.sentinel_dir

        # La dirección desde la que NO puede recibir = la dirección del sentinel
        # (solo para sentinels cardinales; diagonales pueden recibir de los 4 lados)
        is_diagonal = sentinel_dir in (
            Direction.NORTHEAST, Direction.SOUTHEAST,
            Direction.SOUTHWEST, Direction.NORTHWEST,
        )

        best = None
        best_dist = 10**9
        my_pos = c.get_position()

        for d in _CARDINAL_DIRS:
            adj_pos = sentinel_pos.add(d)
            if not _is_in_bounds(c, adj_pos) or not c.is_in_vision(adj_pos):
                continue

            # Si el sentinel es cardinal, no puede recibir desde su dirección de apunte
            if not is_diagonal:
                # La casilla en la dirección de apunte del sentinel
                blocked_pos = sentinel_pos.add(sentinel_dir)
                if adj_pos == blocked_pos:
                    continue

            bid = c.get_tile_building_id(adj_pos)
            if bid is None:
                continue

            etype = c.get_entity_type(bid)
            if etype not in _CONVEYOR_TYPES:
                continue

            # Verificar que la salida del conveyor apunta hacia el sentinel
            if etype == EntityType.BRIDGE:
                bridge_target = c.get_bridge_target(bid)
                if bridge_target != sentinel_pos:
                    continue
            elif etype == EntityType.SPLITTER:
                # Los splitters alternan salida: si la dirección principal
                # o las adyacentes apuntan al sentinel, vale
                splitter_dir = c.get_direction(bid)
                output_positions = [
                    adj_pos.add(splitter_dir),
                    adj_pos.add(splitter_dir.rotate_left()),
                    adj_pos.add(splitter_dir.rotate_right()),
                ]
                if sentinel_pos not in output_positions:
                    continue
            else:
                # Conveyor normal / armoured: su dirección de salida
                conv_dir = c.get_direction(bid)
                output_pos = adj_pos.add(conv_dir)
                if output_pos != sentinel_pos:
                    continue

            dist = my_pos.distance_squared(adj_pos)
            if dist < best_dist:
                best_dist = dist
                best = (bid, adj_pos)

        return best

    def _find_adjacent_gunner_pos(self, c: Controller) -> tuple[Position, Direction] | None:
        """
        Busca en las 4 casillas adyacentes (cardinales) al sentinel
        una posición donde se pueda construir un gunner que dispare al sentinel.
        
        Prioriza casillas vacías/walkables y verifica con can_fire_from().
        """
        if self.sentinel_pos is None:
            return None

        sentinel_pos = self.sentinel_pos
        my_pos = c.get_position()
        candidates = []

        for d in _ALL_DIRS:
            adj_pos = sentinel_pos.add(d)
            if not _is_in_bounds(c, adj_pos) or not c.is_in_vision(adj_pos):
                continue

            dir_to_sentinel = adj_pos.direction_to(sentinel_pos)

            # Verificar que un gunner aquí podría disparar al sentinel
            if not c.can_fire_from(adj_pos, dir_to_sentinel, EntityType.GUNNER, sentinel_pos):
                continue

            if c.is_in_vision(adj_pos):
                if c.get_tile_env(adj_pos) == Environment.WALL:
                    continue

            bid = c.get_tile_building_id(adj_pos) if c.is_in_vision(adj_pos) else None
            walkable = False
            empty = False

            if bid is None:
                empty = True
            else:
                etype = c.get_entity_type(bid)
                if etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR,
                             EntityType.ROAD, EntityType.SPLITTER, EntityType.BRIDGE):
                    walkable = True

            if empty or walkable:
                dist = my_pos.distance_squared(adj_pos)
                # Priorizar vacías sobre walkables
                priority = 0 if empty else 1
                candidates.append((priority, dist, adj_pos, dir_to_sentinel))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]))
        _, _, pos, direction = candidates[0]
        return (pos, direction)

    def _find_best_gunner_direction(self, c: Controller, pos: Position) -> Direction | None:
        """Encuentra la mejor dirección para un gunner en pos que dispare al sentinel."""
        if self.sentinel_pos is None:
            return None

        for d in _ALL_DIRS:
            if d == Direction.CENTRE:
                continue
            if c.can_fire_from(pos, d, EntityType.GUNNER, self.sentinel_pos):
                return d
        return None

    def _compute_danger_zone(self, c: Controller):
        """
        Calcula las casillas en rango de ataque del sentinel.
        Usa get_attackable_tiles_from() para obtener el patrón geométrico.
        """
        self.danger_zone = set()
        if self.sentinel_pos is None or self.sentinel_dir is None:
            return
        try:
            tiles = c.get_attackable_tiles_from(
                self.sentinel_pos, self.sentinel_dir, EntityType.SENTINEL
            )
            for t in tiles:
                self.danger_zone.add((t.x, t.y))
        except Exception:
            pass

    def _compute_feed_chain(self, c: Controller):
        """
        Calcula una cadena de conveyors para alimentar al gunner con titanium,
        evitando la zona de peligro del sentinel.
        
        La cadena sale del gunner por su lado opuesto (no-facing) y va
        alejándose del sentinel, buscando posiciones seguras.
        Los conveyors solo van en cardinal, así que se descomponen diagonales.
        """
        self.feed_chain = []
        self.feed_chain_index = 0

        if self.gunner_build_pos is None or self.gunner_dir is None:
            return
        if self.my_core_pos is None:
            return

        gunner_pos = self.gunner_build_pos
        gunner_dir = self.gunner_dir
        danger = self.danger_zone

        # El gunner recibe recursos por cualquier dirección EXCEPTO su facing
        # Buscar el mejor lado para empezar la cadena:
        # Elegir la casilla cardinal adyacente al gunner que:
        #   1. NO sea la dirección del gunner (no puede recibir por ahí)
        #   2. NO esté en la danger zone del sentinel
        #   3. Esté más cerca de nuestra base
        feed_start = None
        feed_input_dir = None  # dirección desde la que el conveyor entra al gunner
        best_dist = 10**9

        for d in _CARDINAL_DIRS:
            adj = gunner_pos.add(d)
            if not _is_in_bounds(c, adj):
                continue
            # No puede alimentar desde la dirección a la que apunta el gunner
            if d == gunner_dir:
                continue
            # Evitar la zona de peligro
            if (adj.x, adj.y) in danger:
                continue
            # No poner encima del sentinel
            if self.sentinel_pos and adj == self.sentinel_pos:
                continue

            dist = adj.distance_squared(self.my_core_pos)
            if dist < best_dist:
                best_dist = dist
                feed_start = adj
                # Este conveyor debe apuntar HACIA el gunner
                feed_input_dir = d.opposite()  # apunta de adj → gunner

        if feed_start is None:
            return  # No se pudo encontrar entrada segura

        # Primer conveyor: en feed_start apuntando hacia el gunner
        # La dirección del conveyor es hacia donde envía (hacia el gunner)
        self.feed_chain.append((feed_start, feed_input_dir.opposite()))

        # Continuar la cadena desde feed_start hacia nuestra base,
        # evitando la danger zone
        current = feed_start
        max_steps = 20

        for _ in range(max_steps):
            d = current.direction_to(self.my_core_pos)

            # Descomponer diagonal a cardinal
            if d in (Direction.NORTHEAST, Direction.NORTHWEST,
                     Direction.SOUTHEAST, Direction.SOUTHWEST):
                dx = self.my_core_pos.x - current.x
                dy = self.my_core_pos.y - current.y
                if abs(dx) >= abs(dy):
                    d = Direction.EAST if dx > 0 else Direction.WEST
                else:
                    d = Direction.SOUTH if dy > 0 else Direction.NORTH

            next_pos = current.add(d)
            if not _is_in_bounds(c, next_pos):
                break

            # Si llegamos cerca del core, parar
            if next_pos.distance_squared(self.my_core_pos) <= 8:
                break

            # Si está en danger zone, intentar desviar
            if (next_pos.x, next_pos.y) in danger:
                # Probar desviación perpendicular
                found_alt = False
                for alt_d in (d.rotate_left().rotate_left(), d.rotate_right().rotate_right()):
                    # Solo cardinales
                    if alt_d in (Direction.NORTHEAST, Direction.NORTHWEST,
                                 Direction.SOUTHEAST, Direction.SOUTHWEST,
                                 Direction.CENTRE):
                        continue
                    alt_pos = current.add(alt_d)
                    if (_is_in_bounds(c, alt_pos)
                            and (alt_pos.x, alt_pos.y) not in danger):
                        # Conveyor en current apunta hacia alt_pos
                        self.feed_chain.append((alt_pos, alt_d))
                        current = alt_pos
                        found_alt = True
                        break
                if not found_alt:
                    break  # No se puede evitar la danger zone, parar
                continue

            # Conveyor en next_pos apuntando hacia current (hacia el gunner)
            conv_output_dir = next_pos.direction_to(current)
            self.feed_chain.append((next_pos, conv_output_dir))
            current = next_pos

        # Invertir la lista: construir desde el más lejano al más cercano al gunner
        # para que el bot recorra en orden natural
        # NO: construir desde el gunner hacia afuera para que los conveyors
        # vayan encadenándose correctamente
        # La lista ya está en orden correcto (de gunner hacia base)

    def _compute_conveyor_path(self, c: Controller, start: Position) -> list[Position]:
        """
        Calcula posiciones para conveyors desde start hacia nuestra base.
        Genera una línea recta de posiciones cardinales paso a paso.
        """
        if self.my_core_pos is None:
            return []

        path = []
        current = start
        max_steps = 30  # Limitar longitud del camino

        for _ in range(max_steps):
            d = current.direction_to(self.my_core_pos)
            # Solo cardinales para conveyors
            if d in (Direction.NORTHEAST, Direction.NORTHWEST,
                     Direction.SOUTHEAST, Direction.SOUTHWEST):
                # Decompose diagonal: priorizar eje con mayor diferencia
                dx = self.my_core_pos.x - current.x
                dy = self.my_core_pos.y - current.y
                if abs(dx) >= abs(dy):
                    d = Direction.EAST if dx > 0 else Direction.WEST
                else:
                    d = Direction.SOUTH if dy > 0 else Direction.NORTH

            next_pos = current.add(d)
            if not _is_in_bounds(c, next_pos):
                break

            # Si llegamos al core, parar
            if next_pos.distance_squared(self.my_core_pos) <= 8:
                break

            path.append(next_pos)
            current = next_pos

        return path

    def _navigate_to(self, c: Controller, dest: Position):
        """Navegar hacia destino construyendo roads."""
        current = c.get_position()
        d = self.navegador.moveTo(c, dest, four_dirs=False)
        next_pos = current.add(d)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(d):
            c.move(d)
