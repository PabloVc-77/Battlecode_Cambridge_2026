from cambc import Controller, Direction, EntityType, Environment, Position
"""
Mapa bueno para probar: cambc run --watch trucha_v2_2_catapulta trucha_v2_2 labyrinth.map26
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
    """Decodifica el valor del marker a una Position objetivo."""
    return Position(value // 1000, value % 1000)

# ─────────────────────────────────────────────────────────────────────────────
#  LAUNCHER
# ─────────────────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self, c: Controller):
        # Mantenemos inicializacion de bridges si fuese util aunque priorizaremos el core
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

        # ── PRIORIDAD 1: Ayudar a bots aliados atascados ──────────────────────
        if self._try_help_allies(c, my_pos, my_team):
            return  # ya usamos nuestra acción este turno

        # ── PRIORIDAD 2: Atacar enemigos ──────────────────────────────────────
        self._try_attack_enemies(c, my_pos, my_team)

    def _try_help_allies(self, c: Controller, my_pos: Position, my_team: int) -> bool:
        nearby_units = c.get_nearby_units(2)

        for unit_id in nearby_units:
            if c.get_team(unit_id) != my_team:
                continue
            if c.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue

            bot_pos = c.get_position(unit_id)

            # Buscar un marker adyacente al launcher o al bot
            goal, marker_pos = self._find_goal_marker(c, my_pos, bot_pos, my_team)
            if goal is None:
                continue  

            best_target = self._best_launch_target(c, bot_pos, goal)
            if best_target is None:
                # Romper el marker para no atascar al bot
                if marker_pos is not None:
                    if c.can_destroy(marker_pos):
                        c.destroy(marker_pos)
                continue

            # Destruir el marker exitoso
            if marker_pos is not None:
                if c.can_destroy(marker_pos):
                    c.destroy(marker_pos)

            if c.can_launch(bot_pos, best_target):
                c.launch(bot_pos, best_target)
                return True

        return False

    def _find_goal_marker(self, c: Controller, launcher_pos: Position, bot_pos: Position, my_team: int) -> tuple[Position | None, Position | None]:
        search_tiles = set()
        w = c.get_map_width()
        h = c.get_map_height()
        for pos in [launcher_pos, bot_pos]:
            for adj in adjacent_positions(pos):
                if 0 <= adj.x < w and 0 <= adj.y < h:
                    search_tiles.add((adj.x, adj.y))
                
        for x, y in search_tiles:
            adj = Position(x, y)
            if not c.is_in_vision(adj): continue
            bid = c.get_tile_building_id(adj)
            if bid is None:
                continue
            if c.get_entity_type(bid) != EntityType.MARKER:
                continue
            if c.get_team(bid) != my_team:
                continue
            value = c.get_marker_value(bid)
            goal = decode_goal(value)
            return goal, adj
        return None, None

    def _best_launch_target(self, c: Controller, bot_pos: Position, goal: Position) -> Position | None:
        current_dist = dist_sq(bot_pos, goal)
        best_pos: Position | None = None
        best_dist: int = current_dist - MIN_IMPROVEMENT_SQ
        best_dist_to_bot: int = 999999

        candidates = c.get_nearby_tiles()

        for tile in candidates:
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
            elif d == best_dist:
                # En caso de empate hacia la meta, preferimos undershoot o mantener el eje, 
                # reduciendo la distancia al bot para no volar a los lados
                if db < best_dist_to_bot:
                    best_dist_to_bot = db
                    best_pos = tile

        return best_pos

    def _try_attack_enemies(self, c: Controller, my_pos: Position, my_team: int):
        core_pos = self._find_allied_core(c, my_team)

        nearby_units = c.get_nearby_units(2)
        
        # Opcional: ordenar unidades enemigas si las queremos alejar de nuestro bridge
        # units.sort(key=lambda u: self.my_bridge.distance_squared(c.get_position(u)))

        for unit_id in nearby_units:
            if c.get_team(unit_id) == my_team:
                continue

            enemy_pos = c.get_position(unit_id)

            target = self._farthest_from_core(c, enemy_pos, core_pos)
            if target is not None and c.can_launch(enemy_pos, target):
                c.launch(enemy_pos, target)
                return 

    def _find_allied_core(self, c: Controller, my_team: int) -> Position | None:
        nearby_b = c.get_nearby_buildings()
        for bid in nearby_b:
            if c.get_team(bid) == my_team and c.get_entity_type(bid) == EntityType.CORE:
                return c.get_position(bid)
        return None

    def _farthest_from_core(self, c: Controller, bot_pos: Position, core_pos: Position | None) -> Position | None:
        candidates = c.get_nearby_tiles()
            
        best_pos: Position | None = None
        best_dist: int = -1

        for tile in candidates:
            if not c.is_tile_passable(tile):
                continue
            if not c.can_launch(bot_pos, tile):
                continue
            if core_pos is not None:
                d = dist_sq(tile, core_pos)
            else:
                d = dist_sq(tile, bot_pos)  # alejarse todo lo posible si no sabemos dnd esta el core
            
            # Ademas preferimos alejar de nuestro semi_spawn en caso de empate general
            if d > best_dist:
                best_dist = d
                best_pos = tile
        
        # Fallback a la logica original si best_pos sigue siendo None y encontramos a dnd tirar
        if best_pos is None:
            viable = []
            for t in candidates:
                if c.can_launch(bot_pos, t):
                    viable.append(t)
            if viable:
                viable.sort(key=lambda p: self.semi_spawn.distance_squared(p), reverse=True)
                return viable[0]

        return best_pos