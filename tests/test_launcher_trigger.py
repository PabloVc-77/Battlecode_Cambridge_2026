import sys
import os

# Add the bot directory to path
sys.path.append(os.path.abspath('bots/trucha_v2_6'))

try:
    from bignav_a_mem import BugNav
    from cambc import Controller, Position, EntityType, Environment, Direction
    
    # Mocking Controller
    class MockController:
        def __init__(self, pos, resources=[200, 200]):
            self.pos = pos
            self.resources = resources
            self.launcher_built = False
        def get_map_width(self): return 100
        def get_map_height(self): return 100
        def get_nearby_tiles(self): 
            # (13, 13) will be our landing target.
            # (11, 10) will be a wall blocking walking access to (13, 13).
            # (10, 11) will be an EMPTY tile where we can build a launcher.
            return [Position(11, 10), Position(10, 11), Position(13, 13)]
        def get_tile_env(self, pos): 
            p = (pos.x, pos.y)
            if p == (11, 10): return Environment.WALL
            return Environment.EMPTY
        def get_tile_building_id(self, pos): return None
        def get_entity_type(self, id): return None
        def is_tile_passable(self, pos): 
            p = (pos.x, pos.y)
            if p == (10, 10) or p == (10, 11) or p == (13, 13):
                return True
            return False
        def is_tile_empty(self, pos): 
            return self.is_tile_passable(pos)
        def is_in_vision(self, pos): 
            p = (pos.x, pos.y)
            if p == (20, 20): return False
            return True
        def get_position(self, id=None): return self.pos
        def get_global_resources(self): return self.resources
        def can_build_launcher(self, pos): return True
        def build_launcher(self, pos): self.launcher_built = True
        def get_cpu_time_elapsed(self): return 0
        def get_team(self, id=None): return 1
        def can_launch(self, bot_pos, target_pos): return True
        def draw_indicator_dot(self, pos, r, g, b): pass
        def draw_indicator_line(self, p1, p2, r, g, b): pass
        def can_move(self, d): 
            dest = self.pos.add(d)
            return self.is_tile_passable(dest)

    def test_launcher_trigger_blocked():
        current_pos = Position(10, 10)
        goal_pos = Position(20, 20)
        c = MockController(current_pos)
        nav = BugNav()
        nav._init_dims(c)
        
        # Action: moveTo once to set prevGoal
        nav.moveTo(c, goal_pos, False)
        
        # Simulate A* failure for THIS goal
        nav._astar_failed_goal = goal_pos
        nav.wall_steps = 5 
        nav._path = [] # CLEAR the path that A* might have found
        
        # Action: moveTo AGAIN
        nav.moveTo(c, goal_pos, False)
        
        # Assert: Should it have built a launcher?
        if c.launcher_built:
            print("SUCCESS: Launcher built for blocked path with few wall steps.")
            return True
        else:
            print(f"FAILURE: Launcher NOT built. astar_blocked={nav._astar_failed_goal == goal_pos}")
            return False

    if __name__ == "__main__":
        if test_launcher_trigger_blocked():
            sys.exit(0)
        else:
            sys.exit(1)
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
