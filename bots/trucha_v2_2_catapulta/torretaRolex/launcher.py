from cambc import Controller, Direction, EntityType, Environment, Position
"""
Launcher — lanza bots aliados atascados o que pasan cerca con un goal lejano,
y aleja bots enemigos del core propio.

Protocolo de marker (encoding x*1000+y):
  - El bot coloca un marker con su destino deseado (casilla de aterrizaje).
  - El launcher lo lee, calcula el mejor lanzamiento hacia ese destino,
    destruye el marker y lanza al bot.
  - Markers con valor > 100_000 son de otros sistemas (axionita, etc.)
    y se ignoran.
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

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def dist_sq(a: Position, b: Position) -> int:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2

def adjacent_positions(pos: Position):
    result = []
    for d in DIRECTIONS_ALL:
        dx, dy = d.delta()
        result.append(Position(pos.x + dx, pos.y + dy))
    return result

def decode_goal(value: int) -> Position:
    """Decodifica el valor del marker a una Position objetivo (encoding x*1000+y)."""
    return Position(value // 1000, value % 1000)

# ─────────────────────────────────────────────────────────────────────────────
#  LAUNCHER
# ─────────────────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self, c: Controller):
        current = c.get_position()
        self.semi_spawn = current  # fallback por defecto
        self.my_bridge = current   # fallback

        buildings = c.get_nearby_buildings()
        my_bridges = []
        for b in buildings:
            if c.get_entity_type(b) == EntityType.BRIDGE and c.get_team(b) == c.get_team():
                my_bridges.append(b)

        my_bridges.sort(key=lambda p: current.distance_squared(c.get_position(p)))

        if len(my_bridges) > 0:
            my_b = my_bridges[0]
            self.my_bridge = c.get_position(my_b)
            next_bridge = c.get_bridge_target(my_b)

            while c.is_in_vision(next_bridge):
                b_id = c.get_tile_building_id(next_bridge)
                if b_id is None or c.get_entity_type(b_id) != EntityType.BRIDGE:
                    break
                next_bridge = c.get_bridge_target(b_id)

            self.semi_spawn = next_bridge

    def run(self, c: Controller):
        my_pos = c.get_position()
        my_team = c.get_team()

        # ── PRIORIDAD 1: Ayudar a bots aliados (atascados u oportunistas) ─────
        if self._try_help_allies(c, my_pos, my_team):
            return

        # ── PRIORIDAD 2: Atacar enemigos ──────────────────────────────────────
        self._try_attack_enemies(c, my_pos, my_team)

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
            goal, marker_pos = self._find_goal_marker(c, my_pos, bot_pos, my_team)
            if goal is None:
                continue

            best_target = self._best_launch_target(c, bot_pos, goal)
            if best_target is None:
                # No hay lanzamiento útil: destruir el marker para no atascar al bot
                if marker_pos is not None and c.can_destroy(marker_pos):
                    c.destroy(marker_pos)
                continue

            # Destruir el marker antes de lanzar
            if marker_pos is not None and c.can_destroy(marker_pos):
                c.destroy(marker_pos)

            if c.can_launch(bot_pos, best_target):
                c.launch(bot_pos, best_target)
                return True

        return False

    def _find_goal_marker(
        self,
        c: Controller,
        launcher_pos: Position,
        bot_pos: Position,
        my_team: int,
    ) -> tuple[Position | None, Position | None]:
        """
        Busca un marker aliado con encoding x*1000+y en:
          - Casillas adyacentes (8 dirs) al launcher.
          - Casillas adyacentes (8 dirs) al bot.
          - La posición exacta del bot (puede poner marker en dist²=0).
          - La posición exacta del launcher (el bot puede ponerlo ahí también).

        Ignora markers con valor > 100_000 (pertenecen a otros sistemas,
        como los markers de axionita que usan 833*10000+...).

        Devuelve (goal_pos, marker_tile) o (None, None).
        """
        w = c.get_map_width()
        h = c.get_map_height()

        # Conjunto de tiles a inspeccionar (sin duplicados)
        search_tiles: set[tuple[int, int]] = set()

        # Adyacentes al launcher y al bot
        for center in (launcher_pos, bot_pos):
            for adj in adjacent_positions(center):
                if 0 <= adj.x < w and 0 <= adj.y < h:
                    search_tiles.add((adj.x, adj.y))

        # Posición exacta del bot y del launcher (el bot puede colocar el marker aquí)
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
            # Filtrar markers de otros sistemas (axionita: 833*10000+... > 100_000)
            if value > 100_000:
                continue
            goal = decode_goal(value)
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

    def _try_attack_enemies(self, c: Controller, my_pos: Position, my_team: int):
        """Lanza bots enemigos adyacentes lo más lejos posible del core aliado."""
        core_pos = self._find_allied_core(c, my_team)

        for unit_id in c.get_nearby_units(2):
            if c.get_team(unit_id) == my_team:
                continue
            enemy_pos = c.get_position(unit_id)
            target = self._farthest_from_core(c, enemy_pos, core_pos)
            if target is not None and c.can_launch(enemy_pos, target):
                c.launch(enemy_pos, target)
                return

    def _find_allied_core(self, c: Controller, my_team: int) -> Position | None:
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == my_team and c.get_entity_type(bid) == EntityType.CORE:
                return c.get_position(bid)
        return None

    def _farthest_from_core(self, c: Controller, bot_pos: Position,
                             core_pos: Position | None) -> Position | None:
        best_pos: Position | None = None
        best_dist: int = -1

        for tile in c.get_nearby_tiles():
            if not c.is_tile_passable(tile):
                continue
            if not c.can_launch(bot_pos, tile):
                continue
            d = dist_sq(tile, core_pos) if core_pos is not None else dist_sq(tile, bot_pos)
            if d > best_dist:
                best_dist = d
                best_pos = tile

        # Fallback: alejar del semi_spawn
        if best_pos is None:
            viable = [t for t in c.get_nearby_tiles() if c.can_launch(bot_pos, t)]
            if viable:
                viable.sort(key=lambda p: self.semi_spawn.distance_squared(p), reverse=True)
                return viable[0]

        return best_pos