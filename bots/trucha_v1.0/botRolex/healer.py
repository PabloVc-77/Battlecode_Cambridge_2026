from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav

# ---------------------------------------------------------------------------
# Prioridad de curación: menor número = mayor prioridad
# ---------------------------------------------------------------------------
HEAL_PRIORITY: dict[EntityType, int] = {
    EntityType.CORE:               0,
    EntityType.BRIDGE:             1,
    EntityType.SPLITTER:           1,
    EntityType.CONVEYOR:           1,
    EntityType.FOUNDRY:            2,
    EntityType.ARMOURED_CONVEYOR:  2,
    EntityType.LAUNCHER:           3,
    EntityType.SENTINEL:           4,
    EntityType.GUNNER:             5,
    EntityType.BREACH:             6,
    EntityType.HARVESTER:          7,
    EntityType.BARRIER:            8,
    EntityType.ROAD:               9,
}

TRACKED_TYPES: frozenset[EntityType] = frozenset({
    EntityType.CORE,
    EntityType.FOUNDRY,
    EntityType.HARVESTER,
    EntityType.LAUNCHER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.CONVEYOR,
    EntityType.BARRIER,
})

WALKABLE_TYPES: frozenset[EntityType] = frozenset({
    EntityType.CORE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.ROAD,
    EntityType.SPLITTER,
})

TRANSPORT_TYPES: frozenset[EntityType] = frozenset({
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
})


def _entity_priority(entity_type: EntityType) -> int:
    return HEAL_PRIORITY.get(entity_type, 99)


class Healer:
    def __init__(self, c: Controller):
        self.navegador = bugnav.BugNav()

        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        # Diccionario pos -> EntityType de todos los edificios aliados conocidos
        self.known_buildings: dict[Position, EntityType] = {}

        # ── Patrulla ────────────────────────────────────────────────────────
        # Ruta actual de patrulla: lista de posiciones waypoints (ida: base → harvester)
        self.patrol_route: list[Position] = []
        # Índice del waypoint al que nos dirigimos ahora
        self.patrol_index: int = 0
        # Dirección de recorrido: +1 = hacia el harvester, -1 = de vuelta a la base
        self.patrol_direction: int = 1
        # Índice del end_bridge que usamos en la ruta actual (para rotar entre rutas)
        self._eb_index: int = 0

        # Posición del core (base)
        self.core_pos: Position | None = None

        # end_bridges: casillas de entrada a la base (igual que en builder_new.py)
        self.end_bridges: list[Position] = []

        # Inicializar core y end_bridges
        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE:
                self.core_pos = c.get_position(b)
                break

        if self.core_pos is not None:
            s = self.core_pos
            candidates = [
                s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST),
                s.add(Direction.NORTH).add(Direction.NORTH),
                s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST),
                s.add(Direction.EAST).add(Direction.EAST).add(Direction.NORTH),
                s.add(Direction.EAST).add(Direction.EAST),
                s.add(Direction.EAST).add(Direction.EAST).add(Direction.SOUTH),
                s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST),
                s.add(Direction.SOUTH).add(Direction.SOUTH),
                s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST),
                s.add(Direction.WEST).add(Direction.WEST).add(Direction.NORTH),
                s.add(Direction.WEST).add(Direction.WEST),
                s.add(Direction.WEST).add(Direction.WEST).add(Direction.SOUTH),
            ]
            for v in candidates:
                if self._in_bounds_static(v) and c.get_tile_env(v) != Environment.WALL:
                    self.end_bridges.append(v)

    # -----------------------------------------------------------------------
    # Bounds
    # -----------------------------------------------------------------------

    def _in_bounds_static(self, pos: Position) -> bool:
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _in_bounds(self, pos: Position) -> bool:
        return self._in_bounds_static(pos)

    # -----------------------------------------------------------------------
    # Movimiento
    # -----------------------------------------------------------------------

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not self._in_bounds(dest):
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    # -----------------------------------------------------------------------
    # Actualización del mapa de edificios conocidos
    # -----------------------------------------------------------------------

    def _update_known_buildings(self, c: Controller):
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRACKED_TYPES:
                continue
            pos = c.get_position(bid)
            self.known_buildings[pos] = etype

        to_remove = []
        for pos in self.known_buildings:
            if c.is_in_vision(pos):
                bid = c.get_tile_building_id(pos)
                if bid is None or c.get_team(bid) != c.get_team():
                    to_remove.append(pos)
        for pos in to_remove:
            del self.known_buildings[pos]

    # -----------------------------------------------------------------------
    # Detección de edificios dañados
    # -----------------------------------------------------------------------

    def _get_damaged_targets(self, c: Controller) -> list[tuple[int, int, Position]]:
        current = c.get_position()
        damaged = []
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRACKED_TYPES:
                continue
            if c.get_hp(bid) < c.get_max_hp(bid):
                pos = c.get_position(bid)
                prio = _entity_priority(etype)
                dist = current.distance_squared(pos)
                damaged.append((prio, dist, pos))
        damaged.sort(key=lambda x: (x[0], x[1]))
        return damaged

    # -----------------------------------------------------------------------
    # Construcción de ruta base → harvester siguiendo la cadena de transporte
    # -----------------------------------------------------------------------

    def _follow_chain_from(self, c: Controller, start: Position) -> list[Position]:
        """
        Sigue la cadena de transporte desde `start` (un end_bridge)
        en sentido inverso al flujo de recursos (los recursos van del harvester
        a la base, nosotros vamos de la base al harvester).

        La dirección de cada conveyor/bridge apunta HACIA la base, así que
        seguimos en sentido contrario: desde el end_bridge nos alejamos
        buscando qué edificio apunta a la posición actual.

        Devuelve la ruta [start, ..., harvester_pos] o la cadena hasta donde
        podamos ver.
        """
        route = [start]
        visited: set[Position] = {start}
        if self.patrol_route is not None:
            for p in self.patrol_route:
                visited.add(p)
        MAX_STEPS = 80

        for _ in range(MAX_STEPS):
            current_pos = route[-1]

            # Buscar en los known_buildings qué edificio de transporte aliado
            # "alimenta" current_pos (es decir, su output es current_pos).
            next_pos: Position | None = None

            for pos, etype in self.known_buildings.items():
                if pos in visited:
                    continue
                if etype not in TRANSPORT_TYPES and etype != EntityType.HARVESTER:
                    continue
                if not c.is_in_vision(pos): # no debería de ocurrir
                    continue

                bid = c.get_tile_building_id(pos)
                if bid is None or c.get_team(bid) != c.get_team():
                    continue

                actual_etype = c.get_entity_type(bid)

                # Determinar el output de este edificio
                output_pos: Position | None = None
                if actual_etype == EntityType.BRIDGE:
                    try:
                        output_pos = c.get_bridge_target(bid)
                    except Exception:
                        continue
                elif actual_etype in (EntityType.CONVEYOR,
                                      EntityType.ARMOURED_CONVEYOR,
                                      EntityType.SPLITTER):
                    try:
                        d = c.get_direction(bid)
                        output_pos = pos.add(d)
                    except Exception:
                        continue
                elif actual_etype == EntityType.HARVESTER:
                    # El harvester está adyacente (cardinal) a current_pos
                    # y alimenta a current_pos directamente
                    if pos.distance_squared(current_pos) <= 2:
                        output_pos = current_pos  # el harvester apunta aquí

                if output_pos == current_pos:
                    next_pos = pos
                    break  # tomamos el primero que encontramos

            if next_pos is None:
                break

            visited.add(next_pos)
            route.append(next_pos)

            # Si llegamos a un harvester, terminamos
            bid = c.get_tile_building_id(next_pos)
            if bid is not None and c.get_entity_type(bid) == EntityType.HARVESTER:
                break
        
        route.pop() # quitamos el start
        return route

    def _build_patrol_route(self, c: Controller) -> list[Position]:
        """
        Construye la ruta de patrulla usando el end_bridge indicado por _eb_index.
        Si ese end_bridge no tiene cadena visible, prueba con el siguiente.
        Devuelve lista [core, end_bridge, ..., harvester] o sólo [core] si no hay cadena.
        """
        if not self.end_bridges:
            return [self.core_pos] if self.core_pos else []

        # Probar cada end_bridge comenzando por _eb_index hasta encontrar uno con cadena
        n = len(self.end_bridges)
        for attempt in range(n):
            idx = (self._eb_index + attempt) % n
            eb = self.end_bridges[idx]

            if not c.is_in_vision(eb):
                continue
            bid = c.get_tile_building_id(eb)
            if bid is None or c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue

            chain = self._follow_chain_from(c, eb)
            chain.insert(0, eb)
            if len(chain) > 1:  # al menos end_bridge + un eslabón más
                return chain

        # Sin cadena visible: ir al core y esperar
        self.patrol_direction = 0
        return []

    def _refresh_patrol_route(self, c: Controller, advance_eb: bool = False):
        """
        Reconstruye la ruta. Si advance_eb=True, rotamos al siguiente end_bridge
        para que distintos healers (o el mismo en ciclos sucesivos) cubran distintas rutas.
        """
        if advance_eb and self.end_bridges:
            self._eb_index = (self._eb_index + 1) % len(self.end_bridges)

        new_route = self._build_patrol_route(c)
        if new_route:
            self.patrol_route = new_route
            self.patrol_index = 0
            self.patrol_direction = 1

    # -----------------------------------------------------------------------
    # Movimiento de patrulla
    # -----------------------------------------------------------------------

    def _patrol_move(self, c: Controller):
        current = c.get_position()

        # Reconstruir ruta si está vacía
        if not self.patrol_route or self.patrol_direction == 0:
            self._refresh_patrol_route(c)

        if not self.patrol_route:
            c.draw_indicator_dot(current, 128, 128, 128)
            return
        
        for p in self.patrol_route:
            c.draw_indicator_dot(p, 87, 39, 245) # Azul oscuro

        if current == self.patrol_route[self.patrol_index]:
            self.patrol_index += self.patrol_direction
        self.patrol_index = max(0, min(self.patrol_index, len(self.patrol_route) - 1))

        if self.patrol_direction > 0:
            self.patrol_route.extend(self._follow_chain_from(c, self.patrol_route[len(self.patrol_route) - 1]))

        target = self.patrol_route[self.patrol_index]

        try:
            if c.is_in_vision(target) and c.get_entity_type(c.get_tile_building_id(target)) == EntityType.HARVESTER:
                # Volver a casa?
                self.patrol_direction = -1
                pass
        except Exception:
            # Algo esta roto
            pass

        c.draw_indicator_dot(target, 0, 200, 255)
        c.draw_indicator_line(current, target, 0, 200, 255)

        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
        self._try_move(c, siguiente_dir)

    # -----------------------------------------------------------------------
    # Loop principal
    # -----------------------------------------------------------------------

    def run(self, c: Controller):
        current = c.get_position()

        # 1. Actualizar mapa de edificios conocidos
        self._update_known_buildings(c)

        # 2. AUTO-CURACIÓN: primera prioridad si tenemos daño
        my_hp = c.get_hp()
        my_max_hp = c.get_max_hp()
        if my_hp < my_max_hp and c.can_heal(current):
            c.heal(current)
            c.draw_indicator_dot(current, 255, 50, 50)
            return

        # 3. Buscar edificios aliados dañados en visión
        damaged = self._get_damaged_targets(c)

        if damaged:
            prio, dist_sq, target_pos = damaged[0]
            c.draw_indicator_dot(target_pos, 255, 80, 0)
            c.draw_indicator_line(current, target_pos, 255, 80, 0)

            if c.can_heal(target_pos):
                # En rango — curar directamente (no mover)
                c.heal(target_pos)
                c.draw_indicator_dot(current, 0, 255, 80)
            else:
                # Curar otro objetivo en rango de camino si hay acción libre
                if c.get_action_cooldown() == 0:
                    for _, _, alt_pos in damaged[1:]:
                        if current.distance_squared(alt_pos) <= 2 and c.can_heal(alt_pos):
                            c.heal(alt_pos)
                            break

                # Moverse hacia el objetivo principal
                siguiente_dir = self.navegador.moveTo(c, target_pos, four_dirs=False)
                self._try_move(c, siguiente_dir)
        else:
            # Sin daño — patrullar por la red propia
            c.draw_indicator_dot(current, 0, 200, 255)
            self._patrol_move(c)