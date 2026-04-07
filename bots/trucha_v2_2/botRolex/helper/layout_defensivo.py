"""
layout_defensivo.py
Shared module: BASE_LAYOUT definition + rotation utilities.
Imported by both defensivo.py and builder.py so neither duplicates this logic.
"""
from cambc import Controller, Direction, EntityType, Environment, Position


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
#   dy   dx: -2  -1   0  +1  +2
#   -2:      [  ][vS][F ][vS][  ]
#   -1:      [C>][C ][C ][C ][<C]
#    0:      [C>][C ][C ][C ][<C]  ← node_pos (core center)
#   +1:      [C>][C ][C ][C ][<C]
#   +2:      [  ][^S][F ][^S][  ]
#
# Entry: (dx, dy, EntityType, build_fn, Direction, priority)
#   priority 0 = *Sv resource entries (bridge targets)

BASE_LAYOUT = [
    # Priority 0 — resource entry (bridge targets for builder)
    # SPLITTERS
    (-1, -2, EntityType.SPLITTER, "splitter", Direction.SOUTH,     0),
    ( 1, -2, EntityType.SPLITTER, "splitter", Direction.SOUTH,     0),

    (-1,  2, EntityType.SPLITTER, "splitter", Direction.NORTH,     0),
    ( 1,  2, EntityType.SPLITTER, "splitter", Direction.NORTH,     0),

    # CONVEYORS
    (-2, -1, EntityType.CONVEYOR, "conveyor", Direction.EAST,      0),
    (-2,  0, EntityType.CONVEYOR, "conveyor", Direction.EAST,      0),
    (-2,  1, EntityType.CONVEYOR, "conveyor", Direction.EAST,      0),

    ( 2, -1, EntityType.CONVEYOR, "conveyor", Direction.WEST,      0),
    ( 2,  0, EntityType.CONVEYOR, "conveyor", Direction.WEST,      0),
    ( 2,  1, EntityType.CONVEYOR, "conveyor", Direction.WEST,      0),

    # Priority 3 — FOUNDRY
    ( 0, -2, EntityType.FOUNDRY,  "foundry",  Direction.NORTH,     3),
    ( 0,  2, EntityType.FOUNDRY,  "foundry",  Direction.NORTH,     3),
    
]


# ---------------------------------------------------------------------------
# Rotation system  (Y-down: NORTH = -dy)
# ---------------------------------------------------------------------------
#
# CW screen rotation: (dx,dy) → (−dy, dx)   matrix (0,−1,1,0)
# CCW screen rotation:(dx,dy) → ( dy,−dx)   matrix (0, 1,−1,0)
# Verified: R_CW × R_CW = R180 ✓
#
# Cardinal CW:  N→E, E→S, S→W, W→N
# Diagonal CW:  NE→SE, SE→SW, SW→NW, NW→NE
# (same 90° step, just applied to the diagonal basis)

_MAT = {
    "R0":    ( 1,  0,  0,  1),
    "R_CW":  ( 0, -1,  1,  0),
    "R180":  (-1,  0,  0, -1),
    "R_CCW": ( 0,  1, -1,  0),
}

_DIR_MAP = {
    "R0": {
        Direction.NORTH:     Direction.NORTH,
        Direction.NORTHEAST: Direction.NORTHEAST,
        Direction.EAST:      Direction.EAST,
        Direction.SOUTHEAST: Direction.SOUTHEAST,
        Direction.SOUTH:     Direction.SOUTH,
        Direction.SOUTHWEST: Direction.SOUTHWEST,
        Direction.WEST:      Direction.WEST,
        Direction.NORTHWEST: Direction.NORTHWEST,
    },
    "R_CW": {
        Direction.NORTH:     Direction.EAST,
        Direction.NORTHEAST: Direction.SOUTHEAST,
        Direction.EAST:      Direction.SOUTH,
        Direction.SOUTHEAST: Direction.SOUTHWEST,
        Direction.SOUTH:     Direction.WEST,
        Direction.SOUTHWEST: Direction.NORTHWEST,
        Direction.WEST:      Direction.NORTH,
        Direction.NORTHWEST: Direction.NORTHEAST,
    },
    "R180": {
        Direction.NORTH:     Direction.SOUTH,
        Direction.NORTHEAST: Direction.SOUTHWEST,
        Direction.EAST:      Direction.WEST,
        Direction.SOUTHEAST: Direction.NORTHWEST,
        Direction.SOUTH:     Direction.NORTH,
        Direction.SOUTHWEST: Direction.NORTHEAST,
        Direction.WEST:      Direction.EAST,
        Direction.NORTHWEST: Direction.SOUTHEAST,
    },
    "R_CCW": {
        Direction.NORTH:     Direction.WEST,
        Direction.NORTHEAST: Direction.NORTHWEST,
        Direction.EAST:      Direction.NORTH,
        Direction.SOUTHEAST: Direction.NORTHEAST,
        Direction.SOUTH:     Direction.EAST,
        Direction.SOUTHWEST: Direction.SOUTHEAST,
        Direction.WEST:      Direction.SOUTH,
        Direction.NORTHWEST: Direction.SOUTHWEST,
    },
}

# Where the payload cluster lies after each rotation (sign of centroid).
_ROT_EXTENDS = {
    "R0":    ( 1, -1),
    "R_CW":  ( 1,  1),
    "R180":  (-1,  1),
    "R_CCW": (-1, -1),
}

_ROTATIONS = list(_MAT.keys())


def rotate_offset(dx: int, dy: int, rot: str):
    a, b, c, d = _MAT[rot]
    return a * dx + b * dy, c * dx + d * dy


def rotate_dir(direction: Direction, rot: str) -> Direction:
    return _DIR_MAP[rot].get(direction, direction)


def score_rotation(c: Controller, node_pos: Position, rot: str) -> tuple:
    in_bounds = 0
    for (dx, dy, entity, *_) in BASE_LAYOUT:
        rdx, rdy = rotate_offset(dx, dy, rot)
        slot = Position(node_pos.x + rdx, node_pos.y + rdy)
        if not _is_in_bounds(c, slot):
            continue
        if c.is_in_vision(slot) and c.get_tile_env(slot) == Environment.WALL:
            continue
        if entity == EntityType.FOUNDRY:
            in_bounds += 2
        else:
            in_bounds += 1

    cx = c.get_map_width()  / 2.0
    cy = c.get_map_height() / 2.0
    vec_x = cx - node_pos.x
    vec_y = cy - node_pos.y
    ex, ey = _ROT_EXTENDS[rot]
    dot = vec_x * ex + vec_y * ey

    return (in_bounds, dot)


def choose_rotation(c: Controller, node_pos: Position) -> str:
    return max(_ROTATIONS, key=lambda r: score_rotation(c, node_pos, r))


def build_rotated_layout(rotation: str) -> list:
    result = []
    for (dx, dy, etype, build_fn, direction, priority) in BASE_LAYOUT:
        new_dx, new_dy = rotate_offset(dx, dy, rotation)
        new_dir = rotate_dir(direction, rotation)
        result.append((new_dx, new_dy, etype, build_fn, new_dir, priority))
    return result


def compute_layout_for_core(c: Controller, core_pos: Position) -> dict:
    """
    Compute and return a dict with everything the builder needs:

        {
          'rotation':         str,             e.g. "R_CW"
          'layout':           list of entries  (sorted by priority),
          'layout_positions': set[Position],   all absolute positions in the layout,
          'entry_positions':  list[Position],  priority-0 *Sv positions (bridge targets),
          'axionite_entry':   list[Position],  priority-3 F (foundry)  
        }

    Filters out out-of-bounds and visible WALL tiles from entry_positions.
    Call once in __init__ (or on the first run() tick when core is found).
    """
    rotation = choose_rotation(c, core_pos)
    layout = sorted(build_rotated_layout(rotation), key=lambda e: e[5])

    layout_positions = set()
    entry_positions = []
    axionite_entry = []

    for (dx, dy, etype, build_fn, direction, priority) in layout:
        pos = Position(core_pos.x + dx, core_pos.y + dy)
        if not _is_in_bounds(c, pos):
            continue
        layout_positions.add(pos)
        if priority == 0:
            if c.is_in_vision(pos) and c.get_tile_env(pos) == Environment.WALL:
                continue
            entry_positions.append(pos)
        if etype == EntityType.SPLITTER:
            if c.is_in_vision(pos) and c.get_tile_env(pos) == Environment.WALL:
                continue
            axionite_entry.append(pos)

    return {
        'rotation':         rotation,
        'layout':           layout,
        'layout_positions': layout_positions,
        'entry_positions':  entry_positions,
        'axionite_entry':   axionite_entry
    }