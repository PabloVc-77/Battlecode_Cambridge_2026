import sys
import os

# Add the bot directory to path
sys.path.append(os.path.abspath('bots/trucha_v2_6'))

try:
    from bignav_a_mem import BugNav
    from cambc import Controller, Position, EntityType, Environment
    
    # Mocking Controller
    class MockController:
        def __init__(self, tiles_info):
            self.tiles_info = tiles_info # pos -> (env, building_id, entity_type)
        def get_map_width(self): return 100
        def get_map_height(self): return 100
        def get_nearby_tiles(self): return list(self.tiles_info.keys())
        def get_tile_env(self, pos): return self.tiles_info[pos][0]
        def get_tile_building_id(self, pos): return self.tiles_info[pos][1]
        def get_entity_type(self, id): 
            if id is None: return None
            # Find the entity type for this id in tiles_info
            for pos, info in self.tiles_info.items():
                if info[1] == id:
                    return info[2]
            return None
        def is_tile_passable(self, pos): return True
        def is_tile_empty(self, pos): return self.tiles_info[pos][1] is None
        def get_position(self): return Position(0, 0)

    def test_launcher_mapping():
        # Setup: Launcher at (5, 5)
        pos_launcher = Position(5, 5)
        tiles = {
            pos_launcher: (Environment.EMPTY, 1001, EntityType.LAUNCHER)
        }
        c = MockController(tiles)
        nav = BugNav()
        nav._init_dims(c)
        
        # Action: Update map
        nav._update_map(c)
        
        # Assert: Launcher should be in the persistent map
        if not hasattr(nav, '_map_launchers'):
            print("FAILURE: BugNav has no attribute '_map_launchers'")
            return False
            
        if pos_launcher in nav._map_launchers:
            print("SUCCESS: Launcher found in persistent map.")
            return True
        else:
            print(f"FAILURE: Launcher at {pos_launcher} not found in {nav._map_launchers}")
            return False

    if __name__ == "__main__":
        if test_launcher_mapping():
            sys.exit(0)
        else:
            sys.exit(1)
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
