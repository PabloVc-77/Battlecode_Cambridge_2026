from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_opus as bugnav

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()




# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------
#
# Coordinate system: NORTH = -dy  (Y increases DOWNWARD on screen).
# node_pos = CENTER tile of the 3×3 core.
# Core tiles occupy dx ∈ [-1,+1], dy ∈ [-1,+1].
#
# Diagram (screen top = smaller dy = NORTH):
#
#   dy   dx: -2  -1   0  +1  +2  +3
#   -3:  [  ][T^][  ][T^][  ][  ]
#   -2:  [X ][<S][ F][<S*][*Sv][T>]
#   -1:  [X ][C ][C ][C  ][CYv][  ]
#    0:  [X ][C ][C ][C  ][Sv ][T> ]  ← node_pos (core center)
#   +1:  [X ][C ][C ][C  ][X  ][  ]
#   +2:  [X ][X ][X ][X  ][X  ][  ]
#
# X-blocks: LEFT (dx=-2) and SOUTH/down (dy=+2).
# Payload: RIGHT (+dx) and NORTH/up (-dy).
#
# Entry: (dx, dy, EntityType, build_fn, Direction, priority)

BASE_LAYOUT = [
    # Priority 0 — starred: resource entry splitters
    ( 1, -2, EntityType.SPLITTER, "splitter", Direction.WEST,  0),  # <S*
    ( 2, -2, EntityType.SPLITTER, "splitter", Direction.SOUTH, 0),  # *Sv  SOUTH=+dy toward core

    # Priority 1 — foundry chain
    (-1, -2, EntityType.SPLITTER, "splitter", Direction.WEST,  1),  # <S
    ( 0, -2, EntityType.FOUNDRY,  "foundry",  Direction.NORTH, 1),  # F

    # Priority 2 — conveyor + splitter feeding down toward core
    ( 2, -1, EntityType.CONVEYOR, "conveyor", Direction.SOUTH, 2),  # CYv SOUTH=+dy toward Sv
    ( 2,  0, EntityType.SPLITTER, "splitter", Direction.SOUTH, 2),  # Sv  SOUTH=+dy toward core-bot

    # Priority 3 — sentinels
    (-1, -3, EntityType.SENTINEL, "sentinel", Direction.NORTH, 3),  # T^ upper-left
    ( 1, -3, EntityType.SENTINEL, "sentinel", Direction.NORTH, 3),  # T^ upper-right
    ( 3, -2, EntityType.SENTINEL, "sentinel", Direction.EAST,  3),  # T> right-top
    ( 3,  0, EntityType.SENTINEL, "sentinel", Direction.EAST,  3),  # T> right-bottom
]


# ---------------------------------------------------------------------------
# Rotation system  (Y-down: NORTH = -dy)
# ---------------------------------------------------------------------------
#
# With Y-down, a clockwise rotation on screen sends:
#   NORTH vector (0,-1) → EAST (1,0)    [up-screen → right]
#   EAST  vector (1, 0) → SOUTH (0,1)   [right → down-screen]
#
# This gives matrix CW: (dx,dy) → (−dy, dx)   i.e. (a,b,c,d) = (0,−1,1,0)
# And matrix CCW:       (dx,dy) → ( dy,−dx)   i.e. (a,b,c,d) = (0, 1,−1,0)
#
# Verified: R_CW × R_CW = R180 ✓

_MAT = {
    "R0":    ( 1,  0,  0,  1),
    "R_CW":  ( 0, -1,  1,  0),   # CW  screen Y-down: (dx,dy) → (−dy,  dx)
    "R180":  (-1,  0,  0, -1),
    "R_CCW": ( 0,  1, -1,  0),   # CCW screen Y-down: (dx,dy) → ( dy, −dx)
}

# Direction remappings — effect on cardinal directions under each rotation:
#   CW:  N→E, E→S, S→W, W→N
#   CCW: N→W, W→S, S→E, E→N
_DIR_MAP = {
    "R0":    {Direction.NORTH: Direction.NORTH, Direction.EAST:  Direction.EAST,
              Direction.SOUTH: Direction.SOUTH, Direction.WEST:  Direction.WEST},
    "R_CW":  {Direction.NORTH: Direction.EAST,  Direction.EAST:  Direction.SOUTH,
              Direction.SOUTH: Direction.WEST,  Direction.WEST:  Direction.NORTH},
    "R180":  {Direction.NORTH: Direction.SOUTH, Direction.EAST:  Direction.WEST,
              Direction.SOUTH: Direction.NORTH, Direction.WEST:  Direction.EAST},
    "R_CCW": {Direction.NORTH: Direction.WEST,  Direction.EAST:  Direction.NORTH,
              Direction.SOUTH: Direction.EAST,  Direction.WEST:  Direction.SOUTH},
}

# Sign of payload centroid after each rotation (empirically verified).
# Used to score how well the rotated layout faces the map center.
#   R0    → (+x, −y)   right+north  (payload up-right on screen)
#   R_CW  → (+x, +y)   right+south  (payload down-right on screen)
#   R180  → (−x, +y)   left+south   (payload down-left on screen)
#   R_CCW → (−x, −y)   left+north   (payload up-left on screen)
_ROT_EXTENDS = {
    "R0":    ( 1, -1),
    "R_CW":  ( 1,  1),
    "R180":  (-1,  1),
    "R_CCW": (-1, -1),
}

_ROTATIONS = list(_MAT.keys())


def _rotate_offset(dx: int, dy: int, rot: str):
    a, b, c, d = _MAT[rot]
    return a * dx + b * dy, c * dx + d * dy


def _rotate_dir(direction: Direction, rot: str) -> Direction:
    return _DIR_MAP[rot].get(direction, direction)


def _score_rotation(c: Controller, node_pos: Position, rot: str) -> tuple:
    """
    Score a rotation candidate.
    Primary:   number of layout slots inside map bounds.
    Tiebreak:  dot(core→center, rot_extends) — payload faces map center.
    Higher tuple = better.
    """
    in_bounds = 0
    for (dx, dy, *_) in BASE_LAYOUT:
        rdx, rdy = _rotate_offset(dx, dy, rot)
        slot = Position(node_pos.x + rdx, node_pos.y + rdy)
        if not _is_in_bounds(c, slot):
            continue
        # Penalise slots that are already visible and are WALLs
        if c.is_in_vision(slot) and c.get_tile_env(slot) == Environment.WALL:
            continue
        in_bounds += 1

    cx = c.get_map_width()  / 2.0
    cy = c.get_map_height() / 2.0
    vec_x = cx - node_pos.x   # + = center is to the right
    vec_y = cy - node_pos.y   # + = center is BELOW (Y-down)
    ex, ey = _ROT_EXTENDS[rot]
    dot = vec_x * ex + vec_y * ey

    return (in_bounds, dot)


def _choose_rotation(c: Controller, node_pos: Position) -> str:
    return max(_ROTATIONS, key=lambda r: _score_rotation(c, node_pos, r))


def _build_rotated_layout(rotation: str) -> list:
    result = []
    for (dx, dy, etype, build_fn, direction, priority) in BASE_LAYOUT:
        new_dx, new_dy = _rotate_offset(dx, dy, rotation)
        new_dir = _rotate_dir(direction, rotation)
        result.append((new_dx, new_dy, etype, build_fn, new_dir, priority))
    return result


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def _building_matches(c: Controller, building_id, expected_type: EntityType,
                      expected_dir: Direction) -> bool:
    if building_id is None:
        return False
    actual_type = c.get_entity_type(building_id)
    conveyor_types = (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
    if actual_type in conveyor_types:
        if expected_type not in conveyor_types:
            return False
    elif actual_type != expected_type:
        return False
    directed = (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR,
                EntityType.SPLITTER, EntityType.SENTINEL)
    if expected_type in directed:
        return c.get_direction(building_id) == expected_dir
    return True  # foundry: no direction check


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class Defensivo:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()
        self.my_core = None
        self.rotation = None
        self.layout = None

        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) == EntityType.CORE:
                self.my_core = b
                break

    def run(self, c: Controller):
        # 1) Locate core
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE:
                    self.my_core = b
                    break
        if self.my_core is None:
            return

        node_pos = c.get_position(self.my_core)

        # 2) Choose rotation once
        if self.rotation is None:
            self.rotation = _choose_rotation(c, node_pos)
            self.layout = sorted(
                _build_rotated_layout(self.rotation),
                key=lambda e: e[5]
            )

        # 3) Heal core if damaged
        if (c.get_hp(self.my_core) < c.get_max_hp(self.my_core)
                and c.can_heal(node_pos)):
            c.heal(node_pos)

        # 4) Work on layout
        target = self._find_next_build_target(c, node_pos)
        if target is not None:
            dx, dy, entity_type, build_fn, direction, _p = target
            slot_pos = Position(node_pos.x + dx, node_pos.y + dy)
            c.draw_indicator_dot(slot_pos, 255, 200, 0)
            self._work_on_slot(c, slot_pos, entity_type, build_fn, direction)
        else:
            self._idle_move(c, node_pos)

    def _find_next_build_target(self, c: Controller, node_pos: Position):
        out_of_vision_fallback = None
        for entry in self.layout:
            dx, dy, entity_type, build_fn, direction, _p = entry
            slot_pos = Position(node_pos.x + dx, node_pos.y + dy)

            if not _is_in_bounds(c, slot_pos):
                continue
            if not c.is_in_vision(slot_pos):
                if out_of_vision_fallback is None:
                    out_of_vision_fallback = entry
                continue
            # Skip permanently if the tile is a WALL
            if c.get_tile_env(slot_pos) == Environment.WALL:
                continue

            building_id = c.get_tile_building_id(slot_pos)
            if _building_matches(c, building_id, entity_type, direction):
                continue

            return entry

        return out_of_vision_fallback

    def _work_on_slot(self, c: Controller, slot_pos: Position,
                      entity_type: EntityType, build_fn: str,
                      direction: Direction):
        current = c.get_position()
        building_id = c.get_tile_building_id(slot_pos)

        needs_clear = (building_id is not None
                       and not _building_matches(c, building_id, entity_type, direction))
        if needs_clear:
            if not self._clear_tile(c, slot_pos):
                return

        if not self._try_build(c, slot_pos, build_fn, direction):
            dir_ = self.navegador.moveTo(c, slot_pos, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir_):
                c.move(dir_)

    def _idle_move(self, c: Controller, node_pos: Position):
        current = c.get_position()
        if current.distance_squared(node_pos) > 4:
            direc = self.navegador.moveTo(c, node_pos, four_dirs=False)
            if c.can_move(direc):
                c.move(direc)

    def _try_build(self, c: Controller, pos: Position, build_type: str,
                   direction: Direction) -> bool:
        # Can't build on our own tile — move away first
        if pos == c.get_position():
            dir_ = self.navegador.moveTo(c, c.get_position(self.my_core), four_dirs=False)
            if c.can_move(dir_):
                c.move(dir_)
            return False

        if build_type == "splitter":
            if c.can_build_splitter(pos, direction):
                c.build_splitter(pos, direction)
                return True
        elif build_type == "foundry":
            if c.can_build_foundry(pos):
                c.build_foundry(pos)
                return True
        elif build_type == "conveyor":
            if c.can_build_armoured_conveyor(pos, direction):
                c.build_armoured_conveyor(pos, direction)
                return True
            if c.can_build_conveyor(pos, direction):
                c.build_conveyor(pos, direction)
                return True
        elif build_type == "sentinel":
            if c.can_build_sentinel(pos, direction):
                c.build_sentinel(pos, direction)
                return True
        return False

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        building_id = c.get_tile_building_id(target)
        if building_id is None:
            return True

        current = c.get_position()
        is_ally = c.get_team(building_id) == c.get_team()

        if is_ally:
            if c.can_destroy(target):
                c.destroy(target)
                return True
            dir_ = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir_):
                c.move(dir_)
            return False
        else:
            if current == target:
                if c.can_fire(target):
                    c.fire(target)
                    return c.get_tile_building_id(target) is None
                return False
            if c.is_tile_passable(target):
                dir_ = self.navegador.moveTo(c, target, four_dirs=False)
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                if c.can_move(dir_):
                    c.move(dir_)
            return False