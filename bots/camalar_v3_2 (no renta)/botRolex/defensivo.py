from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav
from botRolex.helper.layout_defensivo import (
    _is_in_bounds, BASE_LAYOUT,
    rotate_offset, rotate_dir,
    choose_rotation, build_rotated_layout, compute_layout_for_core,
)


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
        self.node_position = None
        self.rotation = None
        self.layout = None

        self.entry_points = None
        self.input = False

        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) == EntityType.CORE:
                self.my_core = b
                self.node_position = ct.get_position(b)
                break

    def run(self, c: Controller):
        # 1) Locate core
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE:
                    self.my_core = b
                    self.node_position = c.get_position(b)
                    break
        if self.my_core is None:
            return

        node_pos = self.node_position

        # 2) Choose rotation once — uses shared compute_layout_for_core
        if self.rotation is None:
            result = compute_layout_for_core(c, node_pos)
            self.rotation = result['rotation']
            self.layout = result['layout']
            self.entry_points = result['entry_positions']

        # 2.5) Sense for entry material
        if not self.input:
            for entry in self.entry_points:
                if c.is_in_vision(entry):
                    b_id = c.get_tile_building_id(entry)
                    if b_id is not None and c.get_entity_type(b_id) == EntityType.SPLITTER:
                        if c.get_stored_resource(b_id) is not None:
                            self.input = True
                            break

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
            if c.get_tile_env(slot_pos) == Environment.WALL:
                continue

            building_id = c.get_tile_building_id(slot_pos)
            if _building_matches(c, building_id, entity_type, direction):
                continue
            
            # Evitar poner elementos de prioridad baja (son caros)
            if _p > 2 and not self.input:
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

        if not self._try_build(c, slot_pos, build_fn, direction) and current.distance_squared(slot_pos) > 2:
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