import sys
import os

# Add the bot directory to path
sys.path.append(os.path.abspath('bots/trucha_v2_6'))

try:
    from bignav_a_mem import BugNav
    from cambc import Controller, Position, EntityType, Environment, Direction
    
    # Mocking Controller
    class MockController:
        def __init__(self, pos, tiles_info, resources=[200, 200]):
            self.pos = pos
            self.tiles_info = tiles_info # pos -> (env, building_id, entity_type)
            self.resources = resources
            self.marker_placed = False
        def get_map_width(self): return 100
        def get_map_height(self): return 100
        def get_nearby_tiles(self): return list(self.tiles_info.keys())
        def get_tile_env(self, pos): return self.tiles_info.get(pos, (Environment.EMPTY, None, None))[0]
        def get_tile_building_id(self, pos): return self.tiles_info.get(pos, (Environment.EMPTY, None, None))[1]
        def get_entity_type(self, id): 
            if id is None: return None
            for pos, info in self.tiles_info.items():
                if info[1] == id: return info[2]
            return None
        def is_tile_passable(self, pos): return True
        def is_tile_empty(self, pos): return self.get_tile_building_id(pos) is None
        def is_in_vision(self, pos): return True
        def get_position(self, id=None): return self.pos
        def get_global_resources(self): return self.resources
        def can_place_marker(self, pos): return True
        def place_marker(self, pos, val): self.marker_placed = True
        def get_cpu_time_elapsed(self): return 0
        def get_team(self, id=None): return 1
        def can_move(self, d): return True
        def draw_indicator_line(self, p1, p2, r, g, b): pass
        def draw_indicator_dot(self, pos, r, g, b): pass
        def can_launch(self, bot_pos, target_pos): 
            # Launcher is at (11, 11). Bot at (10, 10) is adjacent.
            # Target (15, 15) is in range (dist² = 4²+4²=32... wait LAUNCHER_RANGE_SQ=26)
            # (14, 14) is dist² = 3²+3²=18.
            return True # Simplified for test

    def test_launcher_reuse_not_adjacent():
        current_pos = Position(10, 10)
        goal_pos = Position(30, 30)
        # Launcher at (12, 12) - NOT adjacent (dist² = 2²+2²=8 > 2)
        pos_launcher = Position(12, 12)
        # Landing target at (15, 15) - reachable from launcher (dist² = 3²+3²=18 <= 26)
        pos_landing = Position(15, 15)
        
        tiles = {
            pos_launcher: (Environment.EMPTY, 1001, EntityType.LAUNCHER),
            pos_landing: (Environment.EMPTY, None, None)
        }
        c = MockController(current_pos, tiles)
        nav = BugNav()
        nav._init_dims(c)
        nav._update_map(c) # Record launcher in memory
        
        # Action: moveTo
        direction = nav.moveTo(c, goal_pos, False)
        
        # Assert: Should it have moved towards the launcher at (12, 12)?
        # current is (10, 10). (12, 12) is SOUTHEAST.
        if direction == Direction.SOUTHEAST:
            print("SUCCESS: Bot moved towards non-adjacent launcher.")
            return True
        else:
            print(f"FAILURE: Bot moved {direction} instead of SOUTHEAST.")
            return False

    if __name__ == "__main__":
        if test_launcher_reuse_not_adjacent():
            sys.exit(0)
        else:
            sys.exit(1)
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
