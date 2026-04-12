import sys
import os
import time

# Add the bot directory to path
sys.path.append(os.path.abspath('bots/trucha_v2_6'))

try:
    from bignav_a_mem import BugNav
    from cambc import Controller, Position, EntityType, Environment, Direction
    
    # Mocking Controller
    class MockController:
        def __init__(self, pos, tiles_info):
            self.pos = pos
            self.tiles_info = tiles_info
            self.start_time = time.perf_counter()
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
        def get_global_resources(self): return [500, 500]
        def can_place_marker(self, pos): return True
        def place_marker(self, pos, val): pass
        def get_cpu_time_elapsed(self): 
            return int((time.perf_counter() - self.start_time) * 1_000_000)
        def get_team(self, id=None): return 1
        def can_move(self, d): return True
        def draw_indicator_line(self, p1, p2, r, g, b): pass
        def draw_indicator_dot(self, pos, r, g, b): pass
        def can_launch(self, bot_pos, target_pos): return True

    def benchmark_moveto():
        current_pos = Position(10, 10)
        goal_pos = Position(50, 50)
        
        # Populate vision with some tiles and launchers
        tiles = {}
        for x in range(current_pos.x - 5, current_pos.x + 6):
            for y in range(current_pos.y - 5, current_pos.y + 6):
                p = Position(x, y)
                tiles[p] = (Environment.EMPTY, None, None)
        
        # Add 100 launchers (most out of vision, some in vision)
        for i in range(100):
            p = Position(i % 100, i // 100)
            tiles[p] = (Environment.EMPTY, 2000 + i, EntityType.LAUNCHER)
        
        c = MockController(current_pos, tiles)
        nav = BugNav()
        nav._init_dims(c)
        nav._update_map(c)
        
        # Warmup
        nav.moveTo(c, goal_pos, False)
        
        # Benchmark 100 iterations
        start = time.perf_counter()
        for _ in range(100):
            c.start_time = time.perf_counter() # Reset per-tick CPU clock
            nav.moveTo(c, goal_pos, False)
        end = time.perf_counter()
        
        avg_time_ms = (end - start) / 100 * 1000
        avg_time_us = avg_time_ms * 1000
        print(f"Benchmark: moveTo average time = {avg_time_ms:.4f} ms ({avg_time_us:.2f} us)")
        
        if avg_time_ms < 1.0:
            print("PERFORMANCE SUCCESS: moveTo is well under 1ms.")
            return True
        else:
            print("PERFORMANCE WARNING: moveTo is over 1ms.")
            return False

    if __name__ == "__main__":
        benchmark_moveto()
            
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
