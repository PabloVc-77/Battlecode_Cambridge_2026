"""
BugNav 2.0 — mejoras sobre la versión original
"""
from cambc import Controller, Direction, Position, EntityType
import math
import random

def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0

def _can_move(c: Controller, d: Direction) -> bool:
    if d == Direction.CENTRE:
        return False
    nxt = c.get_position().add(d)
    w, h = c.get_map_width(), c.get_map_height()
    if not (0 <= nxt.x < w and 0 <= nxt.y < h):
        return False
    
    barrier = c.get_tile_building_id(nxt)
    if barrier is not None and c.get_entity_type(barrier) == EntityType.BARRIER and c.get_team(barrier) == c.get_team():
        return True
    return c.can_move(d) or c.is_tile_empty(nxt) or c.is_tile_passable(nxt)

_ALL_DIRS = [
    Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
    Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST,
]
_CARD_DIRS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

def _astar(c: Controller, start: Position, goal: Position, max_nodes: int = 150) -> list:
    w, h = c.get_map_width(), c.get_map_height()
    open_list = [(0.0, 0.0, start, [])]
    g_best = {start: 0.0}
    nodes = 0
    while open_list and nodes < max_nodes:
        open_list.sort(key=lambda x: x[0])
        f, g, pos, path = open_list.pop(0)
        nodes += 1
        if pos == goal:
            return path
        for d in _ALL_DIRS:
            nb = pos.add(d)
            if not (0 <= nb.x < w and 0 <= nb.y < h):
                continue
            if not c.is_in_vision(nb):
                continue
            if not (c.is_tile_passable(nb) or c.is_tile_empty(nb)):
                continue
            step = 1.414 if _is_diagonal(d) else 1.0
            ng = g + step
            if ng >= g_best.get(nb, float("inf")):
                continue
            g_best[nb] = ng
            h_val = math.sqrt(nb.distance_squared(goal))
            open_list.append((ng + h_val, ng, nb, path + [d]))
    return []


class BugNav:
    def __init__(self):
        self.prevGoal = None
        self.start = None
        self.mode = "GOAL"
        self._use_left_hand = True
        self._hand_switches = 0
        self._MAX_HAND_SWITCHES = 3
        self.hitPoint = None
        self.hitDist = float("inf")
        self.prevWallDir = Direction.CENTRE
        self.visitedStates = set()
        self.wall_steps = 0
        self.max_wall_steps = 300
        self.mline_epsilon = 1.5
        self._bfs_path_to = []
        self._bfs_path_explore = []
        self._visited = set()
        self._frontiers = set()
        self._explore_target = None
        self._MAX_VISITED = 2000
        self.dvd = None
        self.fdirs = _CARD_DIRS
        self.dirs = _ALL_DIRS

    def reset(self):
        self.mode = "GOAL"
        self.hitPoint = None
        self.hitDist = float("inf")
        self.prevWallDir = Direction.CENTRE
        self.visitedStates.clear()
        self.wall_steps = 0

    def _switch_hand(self):
        self._use_left_hand = not self._use_left_hand
        self._hand_switches += 1
        self.visitedStates.clear()
        self.wall_steps = 0

    def is_reachable(self, c: Controller, goal: Position) -> bool:
        current = c.get_position()
        if current == goal:
            return True
        w, h = c.get_map_width(), c.get_map_height()
        parent = {current: None}
        queue = [current]
        nodes = 0
        while queue and nodes < 200:
            pos = queue.pop(0)
            nodes += 1
            if pos == goal:
                return True
            for d in _ALL_DIRS:
                nb = pos.add(d)
                if (nb not in parent
                        and 0 <= nb.x < w and 0 <= nb.y < h
                        and c.is_in_vision(nb)
                        and (c.is_tile_passable(nb) or c.is_tile_empty(nb))):
                    parent[nb] = (pos, d)
                    queue.append(nb)
        return False

    def moveTo(self, c: Controller, goal: Position, four_dirs: bool) -> Direction:
        current = c.get_position()
        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0
            self._bfs_path_to = []

        # A* principal — recalcular si el próximo paso está bloqueado
        if self._bfs_path_to and not _can_move(c, self._bfs_path_to[0]):
            self._bfs_path_to = []
        if not self._bfs_path_to:
            self._bfs_path_to = _astar(c, current, goal, max_nodes=150)

        if self._bfs_path_to:
            nxt = self._bfs_path_to[0]
            if four_dirs and _is_diagonal(nxt):
                alt = nxt.rotate_left()
                if _can_move(c, alt):
                    self._bfs_path_to = []
                    return alt
                alt = nxt.rotate_right()
                if _can_move(c, alt):
                    self._bfs_path_to = []
                    return alt
                self._bfs_path_to = []
            else:
                if _can_move(c, nxt):
                    self._bfs_path_to.pop(0)
                    c.draw_indicator_line(current, current.add(nxt), 245, 39, 245)
                    return nxt
                else:
                    self._bfs_path_to = []

        return self._bugnav_step(c, goal, four_dirs)

    def _bugnav_step(self, c: Controller, goal: Position, four_dirs: bool) -> Direction:
        current = c.get_position()
        if self.mode == "GOAL":
            dir_to_goal = current.direction_to(goal)
            if four_dirs and _is_diagonal(dir_to_goal):
                dl = dir_to_goal.rotate_left()
                dr = dir_to_goal.rotate_right()
                if _can_move(c, dl):
                    return dl
                if _can_move(c, dr):
                    return dr
            else:
                if _can_move(c, dir_to_goal):
                    return dir_to_goal
            self.mode = "WALL"
            self.hitPoint = current
            self.hitDist = current.distance_squared(goal)
            self.prevWallDir = self._cardinal_towards(current, goal)
            self.wall_steps = 0
            self.visitedStates.clear()

        c.draw_indicator_dot(current, 245, 63, 39)
        next_dir = self._follow_wall(c, four_dirs)
        next_pos = current.add(next_dir)

        state_key = (current.x, current.y, next_dir.value)
        if state_key in self.visitedStates:
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
                self.hitDist = current.distance_squared(goal)
            else:
                result = self._greedy_step(c, current, goal, four_dirs)
                self.reset()
                self._hand_switches = 0
                return result

        self.visitedStates.add(state_key)
        self.wall_steps += 1
        if self.wall_steps > self.max_wall_steps:
            result = self._greedy_step(c, current, goal, four_dirs)
            self.reset()
            return result

        if (next_dir != Direction.CENTRE
                and self._on_mline(next_pos, c)
                and next_pos.distance_squared(goal) < self.hitDist):
            self.mode = "GOAL"
            self.visitedStates.clear()
            self.hitDist = next_pos.distance_squared(goal)

        return next_dir

    def _follow_wall(self, c: Controller, four_dirs: bool) -> Direction:
        if self.prevWallDir == Direction.CENTRE:
            return Direction.CENTRE
        d = self.prevWallDir
        if self._use_left_hand:
            start_d = d.rotate_left().rotate_left()
            for _ in range(8):
                if not (four_dirs and _is_diagonal(start_d)):
                    if _can_move(c, start_d):
                        self.prevWallDir = start_d
                        return start_d
                start_d = start_d.rotate_right()
        else:
            start_d = d.rotate_right().rotate_right()
            for _ in range(8):
                if not (four_dirs and _is_diagonal(start_d)):
                    if _can_move(c, start_d):
                        self.prevWallDir = start_d
                        return start_d
                start_d = start_d.rotate_left()
        return Direction.CENTRE

    def _cardinal_towards(self, pos: Position, goal: Position) -> Direction:
        dx = goal.x - pos.x
        dy = goal.y - pos.y
        if abs(dx) >= abs(dy):
            return Direction.EAST if dx > 0 else Direction.WEST
        return Direction.SOUTH if dy > 0 else Direction.NORTH

    def _on_mline(self, p: Position, c: Controller) -> bool:
        if self.start is None or self.prevGoal is None:
            return False
        sx, sy = self.start.x, self.start.y
        gx, gy = self.prevGoal.x, self.prevGoal.y
        px, py = p.x, p.y
        dx, dy = gx - sx, gy - sy
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return p == self.start
        t = ((px - sx) * dx + (py - sy) * dy) / length_sq
        if t < 0.0 or t > 1.0:
            return False
        cx_ = sx + t * dx
        cy_ = sy + t * dy
        dist_perp = math.sqrt((px - cx_) ** 2 + (py - cy_) ** 2)
        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)
        return dist_perp < self.mline_epsilon

    def _greedy_step(self, c: Controller, current: Position,
                     goal: Position, four_dirs: bool) -> Direction:
        dirs_list = _CARD_DIRS if four_dirs else _ALL_DIRS
        best_dir = Direction.CENTRE
        best_dist = current.distance_squared(goal)
        for d in dirs_list:
            if _can_move(c, d):
                nd = current.add(d).distance_squared(goal)
                if nd < best_dist:
                    best_dist = nd
                    best_dir = d
        if best_dir == Direction.CENTRE:
            for d in dirs_list:
                if _can_move(c, d):
                    return d
        return best_dir

    def moveDvD(self, c: Controller, four_dirs: bool) -> Direction:
        dirs_list = _CARD_DIRS if four_dirs else _ALL_DIRS
        if self.dvd is None:
            self.dvd = random.choice(dirs_list)
        if _can_move(c, self.dvd):
            return self.dvd
        self.dvd = random.choice(dirs_list)
        return self.dvd

    def _update_exploration(self, c: Controller):
        w, h = c.get_map_width(), c.get_map_height()
        for pos in c.get_nearby_tiles():
            if pos not in self._visited:
                self._visited.add(pos)
                self._frontiers.discard(pos)
                for d in _ALL_DIRS:
                    nb = pos.add(d)
                    if (0 <= nb.x < w and 0 <= nb.y < h
                            and nb not in self._visited
                            and c.is_in_vision(nb)
                            and (c.is_tile_passable(nb) or c.is_tile_empty(nb))):
                        self._frontiers.add(nb)
        if len(self._visited) > self._MAX_VISITED:
            current = c.get_position()
            sorted_v = sorted(self._visited, key=lambda p: current.distance_squared(p))
            self._visited = set(sorted_v[:self._MAX_VISITED // 2])

    def _pick_explore_target(self, c: Controller):
        if not self._frontiers:
            return None
        current = c.get_position()
        return min(self._frontiers, key=lambda p: current.distance_squared(p))

    def moveExplore(self, c: Controller, four_dirs: bool = False) -> Direction:
        self._update_exploration(c)
        current = c.get_position()

        # Descartar al llegar — NO al ver (bug original corregido)
        if (self._explore_target is None
                or current == self._explore_target
                or self._explore_target in self._visited):
            self._explore_target = None
            self._bfs_path_explore = []

        if self._explore_target is None:
            self._explore_target = self._pick_explore_target(c)
            self._bfs_path_explore = []
            if self._explore_target is None:
                return self.moveDvD(c, four_dirs)

        goal = self._explore_target

        if self._bfs_path_explore and not _can_move(c, self._bfs_path_explore[0]):
            self._bfs_path_explore = []
        if not self._bfs_path_explore:
            self._bfs_path_explore = _astar(c, current, goal, max_nodes=150)

        if self._bfs_path_explore:
            nxt = self._bfs_path_explore[0]
            if _can_move(c, nxt):
                self._bfs_path_explore.pop(0)
                return nxt
            else:
                self._bfs_path_explore = []

        # BugNav fallback para explore — actualiza prevGoal independientemente
        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0

        return self._bugnav_step(c, goal, four_dirs)