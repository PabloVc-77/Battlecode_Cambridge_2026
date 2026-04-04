from cambc import Controller, Direction, EntityType, Position
import bignav_opus as bugnav

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


# ---------------------------------------------------------------------------
# Base layout definition
# ---------------------------------------------------------------------------
#
# Origin = nodePosition. The layout extends toward +x and +y.
# X-blocks (walls/edge) occupy the -x and -y side.
#
#  dy  dx: -1   0   +1  +2  +3  +4
#  +3      [ ] [T^] [ ] [T^][ ] [ ]
#  +2      [X] [<S] [F] [<S*][*Sv][T>]
#  +1      [X] [C]  [C] [C] [CYv][ ]
#   0      [X] [C]  [C] [C] [Sv] [T>]
#  -1      [X] [C]  [C] [C] [X]  [ ]
#  -2      [X] [X]  [X] [X] [X]  [ ]
#
# Sentinels point AWAY from the X-block side:
#   T^ → NORTH  (away from -y)
#   T> → EAST   (away from -x, toward +x)
# After rotation they will keep pointing away from the X-block side,
# which is always the side facing away from the map center → toward center. ✓
#
# Entry format: (dx, dy, EntityType, build_fn, Direction, priority)
#   priority 0 = built first

BASE_LAYOUT = [
    # Priority 0 — starred: resource entry splitters
    ( 2,  2, EntityType.SPLITTER, "splitter", Direction.WEST,  0),  # <S*
    ( 3,  2, EntityType.SPLITTER, "splitter", Direction.SOUTH, 0),  # *Sv

    # Priority 1 — foundry chain
    ( 0,  2, EntityType.SPLITTER, "splitter", Direction.WEST,  1),  # <S
    ( 1,  2, EntityType.FOUNDRY,  "foundry",  Direction.NORTH, 1),  # F

    # Priority 2 — conveyor / splitter feeding resources
    ( 3,  1, EntityType.CONVEYOR, "conveyor", Direction.SOUTH, 2),  # CYv
    ( 3,  0, EntityType.SPLITTER, "splitter", Direction.SOUTH, 2),  # Sv

    # Priority 3 — sentinels
    ( 0,  3, EntityType.SENTINEL, "sentinel", Direction.NORTH, 3),  # T^
    ( 2,  3, EntityType.SENTINEL, "sentinel", Direction.NORTH, 3),  # T^
    ( 4,  2, EntityType.SENTINEL, "sentinel", Direction.EAST,  3),  # T>
    ( 4,  0, EntityType.SENTINEL, "sentinel", Direction.EAST,  3),  # T>
]


# ---------------------------------------------------------------------------
# Rotation system
# ---------------------------------------------------------------------------
#
# Four rotations defined by 2x2 integer matrices and direction remappings.
#
#  R0   → identity          → layout extends +x/+y (X-blocks at -x/-y)
#  R90  → 90° CCW           → layout extends -y/+x (X-blocks at +y/-x)
#  R180 → 180°              → layout extends -x/-y (X-blocks at +x/+y)
#  R270 → 90° CW            → layout extends +y/-x (X-blocks at -y/+x)
#
# Matrix (a,b,c,d): new_dx = a*dx + b*dy,  new_dy = c*dx + d*dy

_ROTATIONS = ["R0", "R90", "R180", "R270"]

_MAT = {
    "R0":   ( 1,  0,  0,  1),
    "R90":  ( 0, -1,  1,  0),
    "R180": (-1,  0,  0, -1),
    "R270": ( 0,  1, -1,  0),
}

_DIR_MAP = {
    "R0":   {Direction.NORTH: Direction.NORTH, Direction.EAST:  Direction.EAST,
             Direction.SOUTH: Direction.SOUTH, Direction.WEST:  Direction.WEST},
    "R90":  {Direction.NORTH: Direction.EAST,  Direction.EAST:  Direction.SOUTH,
             Direction.SOUTH: Direction.WEST,  Direction.WEST:  Direction.NORTH},
    "R180": {Direction.NORTH: Direction.SOUTH, Direction.EAST:  Direction.WEST,
             Direction.SOUTH: Direction.NORTH, Direction.WEST:  Direction.EAST},
    "R270": {Direction.NORTH: Direction.WEST,  Direction.EAST:  Direction.NORTH,
             Direction.SOUTH: Direction.EAST,  Direction.WEST:  Direction.SOUTH},
}

# Direction each rotation makes the layout "extend toward"
# (i.e. the dominant +x/+y corner after rotation, in map coords)
# Used to match rotations to the vector toward the map center.
_ROT_EXTENDS = {
    "R0":   ( 1,  1),   # extends toward +x, +y
    "R90":  (-1,  1),   # extends toward -x, +y
    "R180": (-1, -1),   # extends toward -x, -y
    "R270": ( 1, -1),   # extends toward +x, -y
}


def _rotate_offset(dx: int, dy: int, rot: str):
    a, b, c, d = _MAT[rot]
    return a * dx + b * dy, c * dx + d * dy


def _rotate_dir(direction: Direction, rot: str) -> Direction:
    return _DIR_MAP[rot].get(direction, direction)


def _score_rotation(c: Controller, node_pos: Position, rot: str) -> tuple:
    """
    Score a rotation candidate. Returns (in_bounds_count, dot_product).
    Higher is better. We pick the rotation with the most slots in-bounds,
    breaking ties by how well the layout faces the map center.
    """
    # Count slots that fall inside the map
    in_bounds = 0
    for (dx, dy, *_) in BASE_LAYOUT:
        new_dx, new_dy = _rotate_offset(dx, dy, rot)
        pos = Position(node_pos.x + new_dx, node_pos.y + new_dy)
        if _is_in_bounds(c, pos):
            in_bounds += 1

    # Dot product: how well does this rotation's "extend" direction
    # align with the vector from the core toward the map center?
    cx = c.get_map_width()  / 2.0
    cy = c.get_map_height() / 2.0
    vec_x = cx - node_pos.x
    vec_y = cy - node_pos.y
    ex, ey = _ROT_EXTENDS[rot]
    dot = vec_x * ex + vec_y * ey

    return (in_bounds, dot)


def _choose_rotation(c: Controller, node_pos: Position) -> str:
    """
    Pick the rotation that:
      1. Maximises the number of layout slots inside the map (primary criterion).
      2. Aligns the layout's growth direction with the vector core→map_center
         (tiebreaker — ensures sentinels point toward the center).
    """
    return max(_ROTATIONS, key=lambda r: _score_rotation(c, node_pos, r))


def _build_rotated_layout(rotation: str) -> list:
    result = []
    for (dx, dy, etype, build_fn, direction, priority) in BASE_LAYOUT:
        new_dx, new_dy = _rotate_offset(dx, dy, rotation)
        new_dir = _rotate_dir(direction, rotation)
        result.append((new_dx, new_dy, etype, build_fn, new_dir, priority))
    return result


# ---------------------------------------------------------------------------
# Build dispatcher
# ---------------------------------------------------------------------------

def _try_build(c: Controller, pos: Position, build_type: str,
               direction: Direction) -> bool:
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


def _building_matches(c: Controller, building_id, expected_type: EntityType,
                      expected_dir: Direction) -> bool:
    if building_id is None:
        return False
    actual_type = c.get_entity_type(building_id)
    # Conveyor ↔ armoured conveyor are interchangeable
    conveyor_types = (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
    if actual_type in conveyor_types:
        if expected_type not in conveyor_types:
            return False
    elif actual_type != expected_type:
        return False
    # Directed buildings must also match direction
    directed = (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR,
                EntityType.SPLITTER, EntityType.SENTINEL)
    if expected_type in directed:
        return c.get_direction(building_id) == expected_dir
    return True  # foundry has no direction requirement


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class Defensivo:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()
        self.my_core = None
        self.rotation = None   # determined once on first run
        self.layout = None     # rotated + sorted layout cache

        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) == EntityType.CORE:
                self.my_core = b
                break

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, c: Controller):
        # 1) Locate the core
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE:
                    self.my_core = b
                    break
        if self.my_core is None:
            return

        node_pos = c.get_position(self.my_core)

        # 2) Determine and cache rotation once
        if self.rotation is None:
            self.rotation = _choose_rotation(c, node_pos)
            self.layout = sorted(
                _build_rotated_layout(self.rotation),
                key=lambda e: e[5]  # sort by priority ascending
            )

        # 3) Heal core if damaged
        if (c.get_hp(self.my_core) < c.get_max_hp(self.my_core)
                and c.can_heal(node_pos)):
            c.heal(node_pos)

        # 4) Find and work on next build target
        target = self._find_next_build_target(c, node_pos)
        if target is not None:
            dx, dy, entity_type, build_fn, direction, _priority = target
            slot_pos = Position(node_pos.x + dx, node_pos.y + dy)
            c.draw_indicator_dot(slot_pos, 255, 200, 0)
            self._work_on_slot(c, slot_pos, entity_type, build_fn, direction)
        else:
            self._idle_move(c, node_pos)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_next_build_target(self, c: Controller, node_pos: Position):
        """
        Walk the priority-sorted layout and return the first slot that:
          - Is in-bounds
          - Either is not yet built correctly, or is out of vision (we move toward it)
        Returns None when everything is done.
        """
        out_of_vision_fallback = None

        for entry in self.layout:
            dx, dy, entity_type, build_fn, direction, _priority = entry
            slot_pos = Position(node_pos.x + dx, node_pos.y + dy)

            if not _is_in_bounds(c, slot_pos):
                continue  # slot outside map — skip permanently

            if not c.is_in_vision(slot_pos):
                # Can't evaluate yet; remember as fallback to move toward
                if out_of_vision_fallback is None:
                    out_of_vision_fallback = entry
                continue

            building_id = c.get_tile_building_id(slot_pos)
            if _building_matches(c, building_id, entity_type, direction):
                continue  # slot is correctly built

            return entry  # first incomplete visible slot

        return out_of_vision_fallback  # all visible slots done; move toward unseen ones

    def _work_on_slot(self, c: Controller, slot_pos: Position,
                      entity_type: EntityType, build_fn: str,
                      direction: Direction):
        """Clear any wrong occupant, then build. Move closer if out of range."""
        current = c.get_position()
        building_id = c.get_tile_building_id(slot_pos)

        needs_clear = (building_id is not None
                       and not _building_matches(c, building_id, entity_type, direction))

        if needs_clear:
            if not self._clear_tile(c, slot_pos):
                return  # turn consumed by clear/move

        if not _try_build(c, slot_pos, build_fn, direction):
            # Out of build range — move closer
            dir_ = self.navegador.moveTo(c, slot_pos, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir_):
                c.move(dir_)

    def _idle_move(self, c: Controller, node_pos: Position):
        """Patrol back to core when layout is complete."""
        current = c.get_position()
        if current.distance_squared(node_pos) > 4:
            direc = self.navegador.moveTo(c, node_pos, four_dirs=False)
            if c.can_move(direc):
                c.move(direc)

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        """
        Remove whatever occupies `target`.
          - Allied building:  destroy() if dist² <= 2, else approach.
          - Enemy building:   fire() if standing on it, else walk onto it.
        Returns True when the tile is free, False if more turns are needed.
        """
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