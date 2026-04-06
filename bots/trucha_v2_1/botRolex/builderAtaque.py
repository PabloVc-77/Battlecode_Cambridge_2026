from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav


def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return 0 <= pos.x < w and 0 <= pos.y < h


_TURRET_TYPES = (EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH)

_ALL_DIRS = (
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
)


class Ataque:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()

        self.spawn: Position | None = None
        self.my_core: Position | None = None

        self.enemy_core_pos: Position | None = None
        self.enemy_core_candidates: list[Position] = []
        self.simetry: int = 0

        self.objetivo: Position | None = None

        # True cuando ya destruimos el edificio en objetivo y hay que colocar torreta.
        # Mientras sea True, _scan_enemies NO toca self.objetivo.
        self.pendiente_torreta: bool = False

        # True cuando el objetivo es un destino libre de puente/conveyor enemigo:
        # no hay que destruir nada, ir directo a construir la torreta.
        self.objetivo_es_destino_libre: bool = False

        builds = ct.get_nearby_buildings()
        for b in builds:
            if ct.get_entity_type(b) == EntityType.CORE and ct.get_team(b) == ct.get_team():
                self.spawn = ct.get_position(b)
                self.my_core = self.spawn
                break

        if self.my_core is not None:
            self._init_enemy_candidates(ct.get_map_width(), ct.get_map_height())

    def _init_enemy_candidates(self, w: int, h: int):
        x, y = self.my_core.x, self.my_core.y
        self.enemy_core_candidates = [
            Position(w - 1 - x, y),
            Position(x, h - 1 - y),
            Position(w - 1 - x, h - 1 - y),
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Entrada principal
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        current = c.get_position()

        if c.can_heal(current):
            c.heal(current)

        # Inicialización tardía
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                    self.my_core = c.get_position(b)
                    self.spawn = self.my_core
                    self._init_enemy_candidates(c.get_map_width(), c.get_map_height())
                    break

        # Escanear — respeta pendiente_torreta
        self._scan_enemies(c)

        if self.objetivo is not None:
            c.draw_indicator_dot(current, 255, 80, 0)
            c.draw_indicator_line(current, self.objetivo, 255, 80, 0)
            self._work_objetivo(c)
            return

        if self.enemy_core_pos is None:
            c.draw_indicator_dot(current, 255, 255, 0)
            self._find_enemy_core(c)
        else:
            c.draw_indicator_dot(current, 100, 100, 255)
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # Lógica de "final de línea"
    # ──────────────────────────────────────────────────────────────────────────

    def _get_endpoint_info(self, c: Controller, bid: int) -> tuple[Position, bool] | None:
        """
        Para un conveyor o bridge enemigo, determina cuál es la casilla objetivo
        y si es un "destino libre" (casilla vacía/road a la que apunta) o no.

        Devuelve (objetivo_pos, es_destino_libre) o None si no es un final de línea.

        Reglas:
          - conveyor apunta al core enemigo → objetivo = casilla del conveyor, no libre
          - conveyor apunta a casilla vacía o road → objetivo = casilla destino, libre
          - conveyor apunta a torreta → objetivo = casilla del conveyor, no libre
          - bridge apunta al core enemigo → objetivo = casilla del bridge, no libre
          - bridge apunta a casilla vacía o road → objetivo = casilla destino, libre
          - bridge apunta a torreta → objetivo = casilla del bridge, no libre
        """
        etype = c.get_entity_type(bid)
        building_pos = c.get_position(bid)

        if etype == EntityType.CONVEYOR or etype == EntityType.ARMOURED_CONVEYOR:
            direction = c.get_direction(bid)
            dest = building_pos.add(direction)
        elif etype == EntityType.BRIDGE:
            dest = c.get_bridge_target(bid)
        else:
            return None

        if dest is None or not _is_in_bounds(c, dest):
            return None

        # Para saber qué hay en dest necesitamos tenerlo en visión
        if not c.is_in_vision(dest):
            return None

        dest_bid = c.get_tile_building_id(dest)

        if dest_bid is None:
            # Casilla vacía → destino libre
            return (dest, True)

        dest_etype = c.get_entity_type(dest_bid)
        dest_team = c.get_team(dest_bid)

        # Core enemigo → atacar la propia estructura
        if dest_etype == EntityType.CORE and dest_team != c.get_team():
            return (building_pos, False)

        # Torreta enemiga → atacar la propia estructura
        if dest_etype in _TURRET_TYPES and dest_team != c.get_team():
            return (building_pos, False)

        # Road (cualquier equipo) → destino libre
        if dest_etype == EntityType.ROAD:
            return (dest, True)

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Escaneo
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_enemies(self, c: Controller):
        current = c.get_position()

        # ── Validar objetivo actual ────────────────────────────────────────────
        if self.objetivo is not None:
            if c.is_in_vision(self.objetivo):
                bid = c.get_tile_building_id(self.objetivo)
                if self.pendiente_torreta or self.objetivo_es_destino_libre:
                    # Estamos colocando torreta: solo limpiar si ya está puesta
                    if bid is not None and c.get_team(bid) == c.get_team() \
                            and c.get_entity_type(bid) in _TURRET_TYPES:
                        self.objetivo = None
                        self.pendiente_torreta = False
                        self.objetivo_es_destino_libre = False
                    elif self.hay_enemigo_adyacente(c):
                        # Si hay un enemigo pegado al objetivo, cancelar y buscar otro
                        self.objetivo = None
                        self.pendiente_torreta = False
                        self.objetivo_es_destino_libre = False
                    elif self.objetivo_es_destino_libre and bid is not None \
                            and c.get_team(bid) != c.get_team():
                        # El enemigo puso algo en la casilla destino libre: buscar nuevo
                        self.objetivo = None
                        self.objetivo_es_destino_libre = False
                    return  # no buscar nuevo objetivo mientras hay trabajo pendiente
                else:
                    if bid is None or c.get_team(bid) == c.get_team():
                        self.objetivo = None
                        self.objetivo_es_destino_libre = False
            # Si no está en visión, mantener y acercarse

        # ── Recopilar candidatos de "final de línea" en visión ────────────────
        candidates_libres: list[tuple[Position, float]] = []   # destinos libres
        candidates_destruir: list[tuple[Position, float]] = [] # estructuras a destruir

        _ENDPOINT_TYPES = (
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
        )

        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == c.get_team():
                continue
            if c.get_entity_type(bid) not in _ENDPOINT_TYPES:
                continue
            
            if self.hay_enemigo_adyacente(c):
                continue

            result = self._get_endpoint_info(c, bid)
            if result is None:
                continue

            obj_pos, es_libre = result
            dist = current.distance_squared(obj_pos)
            if es_libre:
                candidates_libres.append((obj_pos, dist))
            else:
                candidates_destruir.append((obj_pos, dist))

        # ── Prioridad 1: destinos libres (colocar torreta directamente) ────────
        if candidates_libres:
            best_pos, best_dist = min(candidates_libres, key=lambda t: t[1])

            if self.objetivo_es_destino_libre and self.objetivo is not None:
                cur_dist = current.distance_squared(self.objetivo)
                if best_dist < cur_dist:
                    self.objetivo = best_pos
                    self.pendiente_torreta = True
            else:
                self.objetivo = best_pos
                self.objetivo_es_destino_libre = True
                self.pendiente_torreta = True
            return

        # Si teníamos objetivo de destino libre pero ya no hay ninguno, limpiar
        if self.objetivo_es_destino_libre:
            self.objetivo = None
            self.objetivo_es_destino_libre = False
            self.pendiente_torreta = False

        # ── Prioridad 2: estructuras a destruir (+ torreta encima) ────────────
        if self.objetivo is not None:
            # Ya tenemos objetivo: cambiar solo si hay uno más cercano
            if candidates_destruir:
                best_pos, best_dist = min(candidates_destruir, key=lambda t: t[1])
                if best_dist < current.distance_squared(self.objetivo):
                    self.objetivo = best_pos
                    self.pendiente_torreta = False
            return

        # Sin objetivo: tomar el más cercano
        if candidates_destruir:
            best_pos, _ = min(candidates_destruir, key=lambda t: t[1])
            self.objetivo = best_pos
            self.objetivo_es_destino_libre = False
            self.pendiente_torreta = False

    # ──────────────────────────────────────────────────────────────────────────
    # Trabajar sobre el objetivo
    # ──────────────────────────────────────────────────────────────────────────

    def _work_objetivo(self, c: Controller):
        current = c.get_position()
        target = self.objetivo

        # ── Acercarse si no está en visión ────────────────────────────────────
        if not c.is_in_vision(target):
            self._navigate_to(c, target)
            return

        bid = c.get_tile_building_id(target)

        # ── Casilla ya tiene nuestra torreta: completado ───────────────────────
        if bid is not None and c.get_team(bid) == c.get_team() \
                and c.get_entity_type(bid) in _TURRET_TYPES:
            self.objetivo = None
            self.pendiente_torreta = False
            self.objetivo_es_destino_libre = False
            return

        # ── Casilla libre o recién vaciada: colocar torreta ───────────────────
        if bid is None or (bid is not None and c.get_team(bid) == c.get_team()
                           and c.get_entity_type(bid) not in _TURRET_TYPES):
            # Si hay un edificio aliado que no es torreta (road, etc.), destruirlo
            if bid is not None and c.get_team(bid) == c.get_team():
                if c.can_destroy(target):
                    c.destroy(target)
                return  # siguiente tick: casilla libre

            # Casilla vacía: activar pendiente si no estaba
            self.pendiente_torreta = True

            # Salir de encima si estamos sobre el target
            if current == target:
                for d in _ALL_DIRS:
                    adj = target.add(d)
                    if _is_in_bounds(c, adj) and c.can_move(d):
                        c.move(d)
                        return
                return  # bloqueado: esperar

            # Acercarse si estamos lejos
            dist_sq = current.distance_squared(target)
            if dist_sq > 2:
                self._navigate_to(c, target)
                return

            # En rango (dist² <= 2) y no encima: construir gunner
            if c.can_build_gunner(target, Direction.NORTH):
                # Orientar el gunner hacia el core enemigo si lo conocemos
                if self.enemy_core_pos is not None:
                    dir_to_enemy = target.direction_to(self.enemy_core_pos)
                else:
                    dir_to_enemy = Direction.NORTH
                if c.can_build_gunner(target, dir_to_enemy):
                    c.build_gunner(target, dir_to_enemy)
                else:
                    # Probar todas las direcciones
                    for d in _ALL_DIRS:
                        if c.can_build_gunner(target, d):
                            c.build_gunner(target, d)
                            break
                self.objetivo = None
                self.pendiente_torreta = False
                self.objetivo_es_destino_libre = False
            return

        # ── Hay edificio enemigo ───────────────────────────────────────────────
        if current == target:
            if c.can_fire(target):
                c.fire(target)
            # Si lo destruimos en este tick, marcar pendiente
            if c.get_tile_building_id(target) is None:
                self.pendiente_torreta = True
            return

        # Movernos encima si es pisable; si no, acercarnos
        moved = False
        if c.is_tile_passable(target):
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
                moved = True
        else:
            if current.distance_squared(target) > 2:
                self._navigate_to(c, target)

        # Si llegamos encima, atacar en el mismo turno
        if moved and c.get_position() == target:
            if c.can_fire(target):
                c.fire(target)
            if c.get_tile_building_id(target) is None:
                self.pendiente_torreta = True

    # ──────────────────────────────────────────────────────────────────────────
    # Búsqueda del core enemigo por simetría
    # ──────────────────────────────────────────────────────────────────────────

    def _find_enemy_core(self, c: Controller):
        if not self.enemy_core_candidates:
            return
        target = self.enemy_core_candidates[self.simetry % len(self.enemy_core_candidates)]
        current = c.get_position()
        c.draw_indicator_line(current, target, 255, 140, 0)
        self._navigate_to(c, target)

        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if bid is not None and c.get_entity_type(bid) == EntityType.CORE \
                    and c.get_team(bid) != c.get_team():
                self.enemy_core_pos = target
            else:
                self.simetry += 1

        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
                self.enemy_core_pos = c.get_position(b)
                break

    # ──────────────────────────────────────────────────────────────────────────
    # Navegar hacia destino construyendo road
    # ──────────────────────────────────────────────────────────────────────────

    def _navigate_to(self, c: Controller, dest: Position):
        current = c.get_position()
        d = self.navegador.moveTo(c, dest, four_dirs=False)
        next_pos = current.add(d)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(d):
            c.move(d)

    # ──────────────────────────────────────────────────────────────────────────
    # Revisar si hay bots enemigos al rededor de un bot aliado 
    # ──────────────────────────────────────────────────────────────────────────
    def hay_enemigo_adyacente(self, c: Controller) -> bool:
        current = c.get_position()
        
        for d in _ALL_DIRS:
            casilla_adyacente = current.add(d)
            if _is_in_bounds(c, casilla_adyacente) and c.is_in_vision(casilla_adyacente):
                bot = c.get_tile_building_id(casilla_adyacente)
                hay_bot = (c.get_entity_type(bot) == EntityType.BUILDER_BOT and c.get_team(bot) != c.get_team())
                if hay_bot:
                    return True
        return False