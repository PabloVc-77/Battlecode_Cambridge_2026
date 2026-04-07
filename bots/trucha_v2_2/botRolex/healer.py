from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav

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
    EntityType.CORE, EntityType.FOUNDRY, EntityType.HARVESTER,
    EntityType.LAUNCHER, EntityType.ARMOURED_CONVEYOR, EntityType.SENTINEL,
    EntityType.GUNNER, EntityType.BREACH, EntityType.BRIDGE,
    EntityType.SPLITTER, EntityType.CONVEYOR, EntityType.BARRIER,
})

TRANSPORT_TYPES: frozenset[EntityType] = frozenset({
    EntityType.BRIDGE, EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER,
})


class Healer:
    def __init__(self, c: Controller):
        self.navegador = bugnav.BugNav()
        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        self.core_pos: Position | None = None
        self.end_bridges: list[Position] = []
        self._eb_index: int = 0

        # Lista de posiciones objetivo de la patrulla.
        # Se construye de forma incremental: empezamos con [end_bridge]
        # y añadimos una posición cada vez que llegamos a la última.
        # Al llegar al final (sin extensión posible), recorremos en orden inverso.
        self.patrol_route: list[Position] = []

        # True = yendo hacia el harvester, False = volviendo al core
        self.going_forward: bool = True

        # Índice actual dentro de patrol_route
        self.patrol_index: int = 0

        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE and c.get_team() == c.get_team(b):
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
                if self._in_bounds(v) and c.get_tile_env(v) != Environment.WALL:
                    self.end_bridges.append(v)

    def _in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

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
                prio = HEAL_PRIORITY.get(etype, 99)
                dist = current.distance_squared(pos)
                damaged.append((prio, dist, pos))
        damaged.sort(key=lambda x: (x[0], x[1]))
        return damaged

    def _find_next_in_chain(self, c: Controller, target_pos: Position) -> Position | None:
        """
        Mira todos los edificios aliados de transporte en visión y devuelve
        la posición de uno cuyo output apunte a target_pos:
          - CONVEYOR / ARMOURED_CONVEYOR / SPLITTER: pos + dir == target_pos
          - BRIDGE: get_bridge_target() == target_pos
        Devuelve None si no hay ninguno.
        """
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype not in TRANSPORT_TYPES:
                continue
            pos = c.get_position(bid)
            if pos == target_pos:
                continue
            if etype == EntityType.BRIDGE:
                try:
                    out = c.get_bridge_target(bid)
                except Exception:
                    continue
            else:  # CONVEYOR, ARMOURED_CONVEYOR, SPLITTER
                try:
                    out = pos.add(c.get_direction(bid))
                except Exception:
                    continue
            if out == target_pos:
                return pos
        return None

    def _start_new_patrol(self, c: Controller):
        """
        Busca un end_bridge activo y arranca la ruta con ese único waypoint.
        Rota entre end_bridges en cada ciclo para cubrir distintas rutas.
        """
        if not self.end_bridges:
            return

        n = len(self.end_bridges)
        for attempt in range(n):
            idx = (self._eb_index + attempt) % n
            eb = self.end_bridges[idx]
            if not c.is_in_vision(eb):
                continue
            bid = c.get_tile_building_id(eb)
            if bid is None or c.get_team(bid) != c.get_team():
                continue
            if c.get_entity_type(bid) not in TRANSPORT_TYPES:
                continue
            self._eb_index = (idx + 1) % n
            self.patrol_route = [eb]
            self.patrol_index = 0
            self.going_forward = True
            return

        self.patrol_route = []

    def _patrol_move(self, c: Controller):
        current = c.get_position()

        if not self.patrol_route:
            self._start_new_patrol(c)
            if not self.patrol_route:
                c.draw_indicator_dot(current, 128, 128, 128)
                return

        self.patrol_index = max(0, min(self.patrol_index, len(self.patrol_route) - 1))
        target = self.patrol_route[self.patrol_index]

        # ── Llegamos al waypoint actual ───────────────────────────────────────
        if current == target:
            if self.going_forward:
                # Estamos encima: buscar el siguiente eslabón desde aquí
                next_pos = self._find_next_in_chain(c, target)

                if next_pos is not None and next_pos not in self.patrol_route:
                    self.patrol_route.append(next_pos)
                    self.patrol_index += 1
                    target = next_pos

                    # Si el siguiente es un harvester, invertir al llegar
                    bid = c.get_tile_building_id(next_pos)
                    if bid is not None and c.get_entity_type(bid) == EntityType.HARVESTER:
                        self.going_forward = False
                else:
                    # Sin más eslabones: invertir dirección
                    self.going_forward = False
                    self.patrol_index -= 1
                    if self.patrol_index < 0:
                        self._start_new_patrol(c)
                        return
                    target = self.patrol_route[self.patrol_index]
            else:
                # Volviendo: retroceder un paso
                self.patrol_index -= 1
                if self.patrol_index < 0:
                    # Llegamos al inicio: nuevo ciclo
                    self._start_new_patrol(c)
                    return
                target = self.patrol_route[self.patrol_index]

        # ── Dibujar y moverse ─────────────────────────────────────────────────
        c.draw_indicator_dot(target, 0, 200, 255)
        c.draw_indicator_line(current, target, 0, 200, 255)
        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
        if c.can_build_road(current.add(siguiente_dir)):
            c.build_road(current.add(siguiente_dir))
        self._try_move(c, siguiente_dir)

    def _has_allied_healer_nearby(self, c: Controller, target_pos: Position) -> bool:
        """
        Devuelve True si ya hay otro bot aliado (distinto de este) a distancia² <= 2
        de target_pos, lo que significa que ya está cubierta esa casilla.
        """
        my_id = c.get_id()
        for uid in c.get_nearby_units():
            if uid == my_id:
                continue
            if c.get_team(uid) != c.get_team():
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            if c.get_position(uid).distance_squared(target_pos) <= 2:
                return True
        return False


    def run(self, c: Controller):
        current = c.get_position()

        # Auto-curación propia
        if c.get_hp() < c.get_max_hp() and c.can_heal(current):
            c.heal(current)
            c.draw_indicator_dot(current, 255, 50, 50)
            return

        # Edificios aliados dañados en visión
        damaged = self._get_damaged_targets(c)

        if damaged:
            # Filtrar objetivos ya cubiertos por otro healer aliado
            uncovered = [
                (prio, dist_sq, pos)
                for prio, dist_sq, pos in damaged
                if not self._has_allied_healer_nearby(c, pos)
            ]

            if not uncovered:
                # Todo está cubierto: patrullar normalmente
                c.draw_indicator_dot(current, 0, 200, 255)
                self._patrol_move(c)
                return

            prio, dist_sq, target_pos = uncovered[0]
            c.draw_indicator_dot(target_pos, 255, 80, 0)
            c.draw_indicator_line(current, target_pos, 255, 80, 0)

            if c.can_heal(target_pos):
                c.heal(target_pos)
                c.draw_indicator_dot(current, 0, 255, 80)
            else:
                if c.get_action_cooldown() == 0:
                    for _, _, alt_pos in uncovered[1:]:
                        if current.distance_squared(alt_pos) <= 2 and c.can_heal(alt_pos):
                            c.heal(alt_pos)
                            break
                siguiente_dir = self.navegador.moveTo(c, target_pos, four_dirs=False)
                if c.can_build_road(current.add(siguiente_dir)):
                    c.build_road(current.add(siguiente_dir))
                self._try_move(c, siguiente_dir)
        else:
            c.draw_indicator_dot(current, 0, 200, 255)
            self._patrol_move(c)