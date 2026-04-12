import sys
import os

# Add the bot directory to path
sys.path.append(os.path.abspath('bots/trucha_v2_6'))

try:
    from bignav_a_mem import BugNav
    from cambc import Controller, Position, EntityType, Environment, Direction
    
    # Mocking Controller
    class MockController:
        def __init__(self, pos, nearby_tiles):
            self.pos = pos
            self.nearby_tiles = nearby_tiles
        def get_map_width(self): return 100
        def get_map_height(self): return 100
        def get_nearby_tiles(self): return self.nearby_tiles
        def get_tile_env(self, pos): return Environment.EMPTY
        def get_tile_building_id(self, pos): return None
        def get_entity_type(self, id): return None
        def is_tile_passable(self, pos): 
            # Make everything unreachable by BFS except current
            p = (pos.x, pos.y)
            if p == (self.pos.x, self.pos.y) or p == (15, 11): return True
            return False
        def is_tile_empty(self, pos): return self.is_tile_passable(pos)
        def is_in_vision(self, pos): return True
        def get_position(self, id=None): return self.pos
        def get_team(self, id=None): return 1

    def test_launcher_range_26():
        current_pos = Position(10, 10)
        goal_pos = Position(20, 20)
        # Target at distance squared 26: (10+5, 10+1) = (15, 11) -> 5²+1² = 26
        target_pos = Position(15, 11)
        
        c = MockController(current_pos, [target_pos])
        nav = BugNav()
        nav._init_dims(c)
        
        landing = nav._find_unreachable_better_tile(c, current_pos, goal_pos, 100, 100)
        
        if landing == target_pos:
            print(f"SUCCESS: Found landing target at range 26: {landing}")
            return True
        else:
            print(f"FAILURE: Did NOT find landing target at range 26. Result: {landing}")
            return False

    if __name__ == "__main__":
        if test_launcher_range_26():
            sys.exit(0)
        else:
            sys.exit(1)
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
