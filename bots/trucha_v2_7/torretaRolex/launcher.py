from cambc import Controller, Direction, EntityType, Environment, Position
"""
Launcher — lanza bots aliados atascados o que pasan cerca con un goal lejano,
y aleja bots enemigos del core propio.

Protocolo de marker (encoding NAV_MARKER_PREFIX + botID*10000 + x*100 + y):
  - El bot coloca un marker con su destino deseado codificando su propio ID
    y la casilla de aterrizaje.
  - El launcher verifica el prefijo, extrae el botID y confirma que el bot
    adyacente tiene ese ID antes de lanzarlo.
  - Markers sin el prefijo NAV_MARKER_PREFIX son de otros sistemas y se ignoran.
"""
# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

DIRECTIONS_ALL = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST,
    Direction.SOUTHEAST, Direction.SOUTH, Direction.SOUTHWEST,
    Direction.WEST, Direction.NORTHWEST,
]

# Distancia² mínima que el lanzamiento debe mejorar respecto a la posición actual
MIN_IMPROVEMENT_SQ = 4

# Encoding de nav markers — debe coincidir con bignav_a_mem.py
NAV_MARKER_PREFIX = 2_000_000_000

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    # Kept for backward compatibility; use self._in_bounds() inside the class.
    w = c.get_map_width()
    h = c.get_map_height()
    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

def dist_sq(a: Position, b: Position) -> int:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2

def adjacent_positions(pos: Position):
    result = []
    for d in DIRECTIONS_ALL:
        dx, dy = d.delta()
        result.append(Position(pos.x + dx, pos.y + dy))
    return result

def is_nav_marker(value: int) -> bool:
    return value >= NAV_MARKER_PREFIX

def decode_nav_marker(value: int) -> tuple[int, Position]:
    """Devuelve (bot_id, landing_position). Solo llamar si is_nav_marker() es True."""
    remainder = value - NAV_MARKER_PREFIX
    bot_id = remainder // 10_000
    coords  = remainder % 10_000
    return bot_id, Position(coords // 100, coords % 100)

# ─────────────────────────────────────────────────────────────────────────────
#  LAUNCHER
# ─────────────────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self, c: Controller):
        current = c.get_position()
        self.semi_core = current  # fallback por defecto

        self.calculate_semi_core(c)

    def run(self, c: Controller):
        my_pos = c.get_position()
        my_team = c.get_team()
        self.calculate_semi_core(c)
        c.draw_indicator_dot(self.semi_core, 245, 39, 39)

        # ── PRIORIDAD 1: Ayudar a bots aliados (atascados u oportunistas) ─────
        if self._try_help_allies(c, my_pos, my_team):
            return

        # ── PRIORIDAD 2: Atacar enemigos ──────────────────────────────────────
        self._try_attack_enemies(c, my_pos, my_team)

    def calculate_semi_core(self, c: Controller) -> None:
        current = c.get_position()
        buildings = c.get_nearby_buildings()
        my_transports = []

        transport_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
        )

        for b in buildings:
            etype = c.get_entity_type(b)
            if etype in transport_types and c.get_team(b) == c.get_team():
                my_transports.append(b)
            if etype == EntityType.CORE and c.get_team(b) == c.get_team():
                self.semi_core = c.get_position(b)
                return

        my_transports.sort(key=lambda p: current.distance_squared(c.get_position(p)))

        if len(my_transports) > 0:
            my_b = my_transports[0]
            next_target = self.next_target(c, my_b=my_b)

            visited: set[tuple[int, int]] = {(next_target.x, next_target.y)}

            while c.is_in_vision(next_target):
                next_b = self.next_target(c, my_b)
                if next_b is None:
                    break
                key = (next_b.x, next_b.y)
                if key in visited:
                    break
                visited.add(key)
                next_target = next_b

            if current.distance_squared(next_target) > current.distance_squared(self.semi_core):
                self.semi_core = next_target
        else:
            if current.distance_squared(current) > current.distance_squared(self.semi_core):
                self.semi_core = current

    def next_target(self, c: Controller, my_b: EntityType):
        etype = c.get_entity_type(my_b)
        check_pos = c.get_position(my_b)
        transport_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
        )

        next_target = None
        if etype == EntityType.BRIDGE:
            next_target = c.get_bridge_target(my_b)
        elif etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            next_target = check_pos.add(c.get_direction(my_b))
        else:
            # Es un splitter
            d = c.get_direction(my_b)
            possible_dirs = [d, d.rotate_left().rotate_left(), d.rotate_right().rotate_right()]
            out_of_vision_fallback = None
            next_target = None
            for dir in possible_dirs:
                ck_pos = check_pos.add(dir)
                if not _is_in_bounds(c, ck_pos):
                    continue
                if not c.is_in_vision(ck_pos):
                    out_of_vision_fallback = ck_pos
                    continue
                if c.get_tile_env(ck_pos) == Environment.WALL:
                    continue

                bid = c.get_tile_building_id(ck_pos)
                etype = c.get_entity_type(bid)
                if etype in transport_types and c.get_team() == c.get_team(bid):
                    if etype in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR):
                        b_dir = c.get_direction(bid)
                        if b_dir == ck_pos.direction_to(check_pos):
                            continue
                    elif etype == EntityType.SPLITTER:
                        b_dir = c.get_direction(bid)
                        if b_dir.opposite() == ck_pos.direction_to(check_pos):
                            continue
                    elif etype == EntityType.BRIDGE:
                        targ = c.get_bridge_target(bid)
                        if targ == check_pos:
                            continue
                    next_target = ck_pos
                    break
                elif c.is_tile_passable(ck_pos):
                    next_target = ck_pos

            if next_target is None:
                next_target = out_of_vision_fallback

        if next_target is None:
            return ck_pos
        
        return next_target


    # ─────────────────────────────────────────────────────────────────────────────
    #  LAUNCHER ALLIES
    # ─────────────────────────────────────────────────────────────────────────────

    def _try_help_allies(self, c: Controller, my_pos: Position, my_team: int) -> bool:
        """
        Busca bots aliados adyacentes (dist²<=2 del launcher) con un marker
        de destino y los lanza hacia ese destino. Funciona tanto para:
          - Bots atascados que colocan marker via jumping mechanic.
          - Bots que pasan cerca y colocan marker via opportunistic launch.
        """
        nearby_units = c.get_nearby_units(2)

        for unit_id in nearby_units:
            if c.get_team(unit_id) != my_team:
                continue
            if c.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue

            bot_pos = c.get_position(unit_id)

            # Buscar marker de destino adyacente al launcher o al bot
            goal, marker_pos = self._find_goal_marker(c, my_pos, bot_pos, unit_id, my_team)
            if goal is None:
                continue

            best_target = self._best_launch_target(c, bot_pos, goal)
            if best_target is None:
                # No hay lanzamiento útil: destruir el marker para no atascar al bot
                if marker_pos is not None and c.can_destroy(marker_pos):
                    c.destroy(marker_pos)
                continue
            
            if c.can_launch(bot_pos, best_target):
                c.launch(bot_pos, best_target)
            else:
                return False

            # Destruir el marker antes de lanzar
            if marker_pos is not None and c.can_destroy(marker_pos):
                c.destroy(marker_pos)

        return True

    def _find_goal_marker(
        self,
        c: Controller,
        launcher_pos: Position,
        bot_pos: Position,
        bot_unit_id: int,
        my_team: int,
    ) -> tuple[Position | None, Position | None]:
        """
        Busca un marker aliado con el prefijo NAV_MARKER_PREFIX en:
          - Casillas adyacentes (8 dirs) al launcher.
          - Casillas adyacentes (8 dirs) al bot.
          - La posición exacta del bot.
          - La posición exacta del launcher.

        Valida que el botID codificado en el marker coincide con bot_unit_id
        para evitar lanzar bots no destinatarios de este launcher.

        Ignora markers que no tengan el prefijo NAV_MARKER_PREFIX.

        Devuelve (goal_pos, marker_tile) o (None, None).
        """
        w = c.get_map_width()
        h = c.get_map_height()

        # Conjunto de tiles a inspeccionar (sin duplicados)
        search_tiles: set[tuple[int, int]] = set()

        for center in (launcher_pos, bot_pos):
            for adj in adjacent_positions(center):
                if 0 <= adj.x < w and 0 <= adj.y < h:
                    search_tiles.add((adj.x, adj.y))

        for pos in (bot_pos, launcher_pos):
            if 0 <= pos.x < w and 0 <= pos.y < h:
                search_tiles.add((pos.x, pos.y))

        for x, y in search_tiles:
            tile = Position(x, y)
            if not c.is_in_vision(tile):
                continue
            bid = c.get_tile_building_id(tile)
            if bid is None:
                continue
            if c.get_entity_type(bid) != EntityType.MARKER:
                continue
            if c.get_team(bid) != my_team:
                continue
            value = c.get_marker_value(bid)
            if not is_nav_marker(value):
                continue
            encoded_bot_id, goal = decode_nav_marker(value)
            # Validar que el marker pertenece exactamente a este bot
            if encoded_bot_id != bot_unit_id:
                continue
            # Validar coordenadas dentro del mapa
            if not (0 <= goal.x < w and 0 <= goal.y < h):
                continue
            return goal, tile

        return None, None

    def _best_launch_target(self, c: Controller, bot_pos: Position, goal: Position) -> Position | None:
        """
        Elige la mejor casilla de aterrizaje para acercar al bot al goal.
        Criterios:
          1. Debe ser pasable y lanzable desde bot_pos.
          2. Debe mejorar la dist² al goal en al menos MIN_IMPROVEMENT_SQ.
          3. Entre candidatos a igual dist² al goal, prefiere el más cercano
             al bot (evita lanzamientos laterales innecesarios).
        """
        current_dist = dist_sq(bot_pos, goal)
        best_pos: Position | None = None
        best_dist: int = current_dist - MIN_IMPROVEMENT_SQ
        best_dist_to_bot: int = 999_999

        for tile in c.get_nearby_tiles():
            if not c.is_tile_passable(tile):
                continue
            if not c.can_launch(bot_pos, tile):
                continue
            d = dist_sq(tile, goal)
            db = dist_sq(tile, bot_pos)

            if d < best_dist:
                best_dist = d
                best_pos = tile
                best_dist_to_bot = db
            elif d == best_dist and db < best_dist_to_bot:
                best_dist_to_bot = db
                best_pos = tile

        return best_pos
    
    # ─────────────────────────────────────────────────────────────────────────────
    #  LAUNCHER ENEMIES
    # ─────────────────────────────────────────────────────────────────────────────

    def _try_attack_enemies(self, c: Controller, my_pos: Position, my_team: int):
        """Lanza bots enemigos adyacentes lo más lejos posible del core aliado."""

        for unit_id in c.get_nearby_units(2):
            if c.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue
            if c.get_team(unit_id) == my_team:
                continue
            enemy_pos = c.get_position(unit_id)
            target = self._farthest_from_core(c, enemy_pos)
            if enemy_pos is not None:
                c.draw_indicator_dot(enemy_pos, 242, 39, 245)
            if target is not None:
                c.draw_indicator_dot(target, 242, 245, 39)

            if target is not None and c.can_launch(enemy_pos, target):
                c.launch(enemy_pos, target)
                return

    def _farthest_from_core(self, c: Controller, bot_pos: Position) -> Position | None:
        viable = [t for t in c.get_nearby_tiles() if c.can_launch(bot_pos, t)]
        if not viable:
            return None
        viable.sort(key=lambda p: self.semi_core.distance_squared(p), reverse=True)
        return viable[0]