import sys
import os

# Add the bot directory to path
sys.path.append(os.path.abspath('bots/trucha_v2_6'))

try:
    from bignav_a_mem import BugNav
    from cambc import Controller, Position, EntityType, Environment, Direction
    
    # Mocking Controller
    class MockController:
        def __init__(self, resources):
            self.resources = resources
            self.launcher_built = False
        def get_map_width(self): return 100
        def get_map_height(self): return 100
        def get_nearby_tiles(self): return [Position(1, 0)]
        def get_tile_env(self, pos): return Environment.EMPTY
        def get_tile_building_id(self, pos): return None
        def get_entity_type(self, id): return None
        def is_tile_passable(self, pos): return True
        def is_tile_empty(self, pos): return True
        def is_in_vision(self, pos): return True
        def get_position(self): return Position(0, 0)
        def get_global_resources(self): return self.resources
        def can_build_launcher(self, pos): return True
        def build_launcher(self, pos): self.launcher_built = True
        def get_cpu_time_elapsed(self): return 0
        def get_team(self, id=None): return 1

    def test_launcher_resource_threshold():
        # Case 1: Resources BELOW threshold (e.g., 50, 50)
        c = MockController([50, 50])
        nav = BugNav()
        nav._init_dims(c)
        nav._jump_state = "BUILDING"
        nav._jump_landing_target = Position(3, 3)
        nav._try_jumping_mechanic(c, Position(10, 10), 100, 100)
        
        if c.launcher_built:
            print("FAILURE: Launcher built despite low resources.")
            return False
        else:
            print("SUCCESS: Launcher NOT built due to low resources.")

        # Case 2: Resources ABOVE threshold (e.g., 150, 150)
        c2 = MockController([150, 150])
        nav2 = BugNav()
        nav2._init_dims(c2)
        nav2._jump_state = "BUILDING"
        nav2._jump_landing_target = Position(3, 3)
        nav2._try_jumping_mechanic(c2, Position(10, 10), 100, 100)
        
        if c2.launcher_built:
            print("SUCCESS: Launcher built with sufficient resources.")
            return True
        else:
            print("FAILURE: Launcher NOT built despite sufficient resources.")
            return False

    if __name__ == "__main__":
        if test_launcher_resource_threshold():
            sys.exit(0)
        else:
            sys.exit(1)
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
