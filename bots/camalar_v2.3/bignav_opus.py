from cambc import Controller, Direction, Position
import math
import random


def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0

def _can_i_move(c: Controller, d: Direction):
    current = c.get_position()
    nextPos = current.add(d)
    w = c.get_map_width()
    h = c.get_map_height()

    if nextPos.x >= 0 and nextPos.x < w and nextPos.y >= 0 and nextPos.y < h:
        return c.can_move(d) or c.is_tile_empty(nextPos) or c.is_tile_passable(nextPos)
    return False


class BugNav:
    def __init__(self):
        self.prevGoal = None
        self.start = None

        # Wall following config
        self._use_left_hand = True
        self._hand_switches = 0
        self._MAX_HAND_SWITCHES = 2

        # Anti-loop + safety
        self.wall_steps = 0
        self.max_wall_steps = 200

        # M-line tolerance
        self.mline_epsilon = 0.7

        # Anti-oscillation
        self.lastLeaveDist = float("inf")

        # Directions
        self.fdirs = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
        self.dirs = [
            Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
            Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
        ]

        # Explorer state
        self._visited = set()
        self._frontiers = set()
        self._explore_target = None

        self._BFS_MAX_DIST = 12 # Rango de Vision
        self._bfs_path = []

        # Random movement state
        self.dvd = None

        self.reset()

    def reset(self):
        self.mode = "GOAL"
        self.hitPoint = None
        self.prevWallDir = Direction.CENTRE
        self.visitedStates = set()
        self.wall_steps = 0

    def _switch_hand(self):
        self._use_left_hand = not self._use_left_hand
        self._hand_switches += 1
        self.visitedStates.clear()
        self.wall_steps = 0

    # ==========================
    # MAIN MOVE
    # ==========================
    def moveTo(self, c: Controller, goal: Position, four_dirs: bool):
        current = c.get_position()

        # Reset si el objetivo cambió
        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0
            self.lastLeaveDist = float("inf")
            self._bfs_path = []

        # Intenta BFS si el goal está dentro del radio
        if current.distance_squared(goal) <= self._BFS_MAX_DIST:
            self._bfs_path = self._bfs_to(c, goal)
            if len(self._bfs_path) > 0:
                next_dir = self._bfs_path[0]
                if _can_i_move(c, next_dir):
                    self._bfs_path.pop(0)
                    c.draw_indicator_line(current, current.add(next_dir), 245, 39, 245)
                    return next_dir
                else:
                    self._bfs_path = []  # camino bloqueado, continúa con BugNav

        # ==========================
        # GO TO GOAL
        # ==========================
        if self.mode == "GOAL":
            dir_to_goal = current.direction_to(goal)

            flag = False
            if four_dirs and _is_diagonal(dir_to_goal):
                flag = True
                dir_to_goal = dir_to_goal.rotate_left()

            if _can_i_move(c, dir_to_goal):
                return dir_to_goal
            elif flag:
                dir_to_goal = dir_to_goal.rotate_right().rotate_right()
                if _can_i_move(c, dir_to_goal):
                    return dir_to_goal

            # Chocamos → iniciar wall following
            self.mode = "WALL"
            self.hitPoint = current
            self.lastLeaveDist = current.distance_squared(goal)
            if four_dirs and _is_diagonal(dir_to_goal):
                dx, dy = dir_to_goal.delta()
                if abs(dx) >= abs(dy):
                    self.prevWallDir = Direction.EAST if dx > 0 else Direction.WEST
                else:
                    self.prevWallDir = Direction.SOUTH if dy > 0 else Direction.NORTH
            else:
                self.prevWallDir = dir_to_goal
            self.wall_steps = 0
            self.visitedStates.clear()

        # ==========================
        # FOLLOW WALL
        # ==========================
        c.draw_indicator_dot(current, 245, 63, 39)

        nextDir = self.followWall(c, four_dirs)
        nextPos = current.add(nextDir)

        # Detección de bucle
        stateKey = (current.x, current.y, str(self.prevWallDir))
        if stateKey in self.visitedStates:
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
                c.draw_indicator_dot(current, 63, 63, 245)
            else:
                greedy = self._greedy_step(c, current, goal, four_dirs)
                self.reset()
                self._hand_switches = 0
                return greedy

        self.visitedStates.add(stateKey)

        # Anti-stuck timeout
        self.wall_steps += 1
        if self.wall_steps > self.max_wall_steps:
            greedy = self._greedy_step(c, current, goal, four_dirs)
            self.reset()
            return greedy

        # Condición de salida Bug2
        if self.shouldLeaveWall(current, nextPos, goal, c):
            self.mode = "GOAL"
            self.visitedStates.clear()
            self.lastLeaveDist = nextPos.distance_squared(goal)

        return nextDir

    # ==========================
    # WALL FOLLOWING
    # ==========================
    def followWall(self, c: Controller, four_dirs: bool):
        current = c.get_position()
        dir = self.prevWallDir

        if dir == Direction.CENTRE:
            return Direction.CENTRE

        if self._use_left_hand:
            d = dir.rotate_left().rotate_left()
            for _ in range(7):
                if not (four_dirs and _is_diagonal(d)):
                    if _can_i_move(c, d):
                        self.prevWallDir = d
                        return d
                d = d.rotate_right()
        else:
            d = dir.rotate_right().rotate_right()
            for _ in range(7):
                if not (four_dirs and _is_diagonal(d)):
                    if _can_i_move(c, d):
                        self.prevWallDir = d
                        return d
                d = d.rotate_left()

        return Direction.CENTRE

    def _wall_priority(self, wall_dir: Direction, left_hand: bool) -> list:
        diag_left  = wall_dir.rotate_left()
        diag_right = wall_dir.rotate_right()
        perp_left  = wall_dir.rotate_left().rotate_left()
        perp_right = wall_dir.rotate_right().rotate_right()
        escape_left  = perp_left.rotate_left()
        escape_right = perp_right.rotate_right()
        opposite = wall_dir.rotate_left().rotate_left().rotate_left().rotate_left()

        if left_hand:
            return [diag_left, diag_right, perp_left, perp_right,
                    escape_left, escape_right, opposite]
        else:
            return [diag_right, diag_left, perp_right, perp_left,
                    escape_right, escape_left, opposite]

    # ==========================
    # LEAVE CONDITION (Bug2)
    # ==========================
    def shouldLeaveWall(self, current: Position, nextPos: Position,
                        goal: Position, c: Controller) -> bool:
        if not self.onMline(nextPos, c):
            return False
        if nextPos.distance_squared(goal) >= self.hitPoint.distance_squared(goal):
            return False
        if nextPos.distance_squared(goal) >= self.lastLeaveDist:
            return False
        return True

    # ==========================
    # M-LINE CHECK
    # ==========================
    def onMline(self, p: Position, c: Controller) -> bool:
        sx, sy = self.start.x, self.start.y
        gx, gy = self.prevGoal.x, self.prevGoal.y
        px, py = p.x, p.y

        dx, dy = gx - sx, gy - sy
        length_sq = dx*dx + dy*dy
        if length_sq == 0:
            return p == self.start

        t = ((px - sx)*dx + (py - sy)*dy) / length_sq
        closest_x = sx + t*dx
        closest_y = sy + t*dy

        dist_perp = math.sqrt((px - closest_x)**2 + (py - closest_y)**2)

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)
        return dist_perp < 1

    # ==========================
    # GREEDY ESCAPE
    # ==========================
    def _greedy_step(self, c: Controller, current: Position,
                     goal: Position, four_dirs: bool):
        dirs_list = self.fdirs if four_dirs else self.dirs

        best_dir = Direction.CENTRE
        best_dist = current.distance_squared(goal)

        for d in dirs_list:
            if _can_i_move(c, d):
                npos = current.add(d)
                nd = npos.distance_squared(goal)
                if nd < best_dist:
                    best_dist = nd
                    best_dir = d

        if best_dir == Direction.CENTRE:
            for d in dirs_list:
                if _can_i_move(c, d):
                    return d

        return best_dir

    # ==========================
    # BFS LOCAL
    # ==========================
    def _bfs_to(self, c: Controller, goal: Position) -> list:
        """
        BFS desde la posición actual hasta goal.
        Solo expande celdas dentro del rango de visión del bot (información fiable).
        Devuelve la lista de direcciones a seguir, o [] si no hay camino visible.
        """
        current = c.get_position()
        w, h = c.get_map_width(), c.get_map_height()

        # parent[pos] = (pos_anterior, direccion_tomada)
        parent = {current: None}
        queue = [current]

        while queue:
            pos = queue.pop(0)
            if pos == goal:
                # Reconstruye el camino hacia atrás
                path = []
                while parent[pos] is not None:
                    prev, d = parent[pos]
                    path.append(d)
                    pos = prev
                path.reverse()
                return path

            for d in self.dirs:
                neighbor = pos.add(d)
                if (neighbor not in parent
                        and 0 <= neighbor.x < w and 0 <= neighbor.y < h
                        and c.is_in_vision(neighbor)        # solo válido desde current
                        and ((c.is_tile_passable(neighbor)) or c.is_tile_empty(neighbor))):  # solo válido desde current
                    parent[neighbor] = (pos, d)
                    queue.append(neighbor)

        return []

    # ==========================
    # RANDOM MOVEMENT
    # ==========================
    def moveDvD(self, c: Controller, four_dirs: bool):
        if self.dvd is None:
            self.dvd = random.choice(self.fdirs if four_dirs else self.dirs)

        if _can_i_move(c, self.dvd):
            return self.dvd

        self.dvd = random.choice(self.fdirs if four_dirs else self.dirs)
        return self.dvd

    # ==========================
    # EXPLORATION
    # ==========================
    def _update_exploration(self, c: Controller):
        """Actualiza visited y frontiers con las celdas visibles ahora mismo."""
        w, h = c.get_map_width(), c.get_map_height()

        for pos in c.get_nearby_tiles():
            if pos not in self._visited:
                self._visited.add(pos)
                self._frontiers.discard(pos)

                for d in self.dirs:
                    neighbor = pos.add(d)
                    if (0 <= neighbor.x < w and 0 <= neighbor.y < h
                            and neighbor not in self._visited
                            and c.is_in_vision(neighbor)
                            and c.is_tile_passable(neighbor)):
                        self._frontiers.add(neighbor)

    def _pick_explore_target(self, c: Controller) -> Position | None:
        """Elige la frontera no visitada más cercana."""
        if not self._frontiers:
            return None
        current = c.get_position()
        return min(self._frontiers, key=lambda p: current.distance_squared(p))

    def _invalidate_explore_target(self, c: Controller) -> bool:
        """Devuelve True si el target actual ya no es válido."""
        t = self._explore_target
        return (t is None
                or c.get_position() == t
                or t in self._visited
                or c.is_in_vision(t))

    def moveExplore(self, c: Controller, four_dirs: bool = False) -> Direction:
        self._update_exploration(c)
        current = c.get_position()

        # Descarta el target si ya no es válido
        if self._invalidate_explore_target(c):
            self._explore_target = None
            self._bfs_path = []
            self.reset()

        # Elige nueva frontera si no hay target
        if self._explore_target is None:
            self._explore_target = self._pick_explore_target(c)
            self._bfs_path = []
            self.reset()

            if self._explore_target is None:
                return self.moveDvD(c, four_dirs)  # fallback: sin fronteras

        # Intenta BFS si el target está dentro del radio y no hay camino calculado
        if (current.distance_squared(self._explore_target) <= self._BFS_MAX_DIST
                and not self._bfs_path):
            self._bfs_path = self._bfs_to(c, self._explore_target)

        # Sigue el camino BFS si existe y el siguiente paso es válido
        if self._bfs_path:
            next_dir = self._bfs_path[0]
            if _can_i_move(c, next_dir):
                self._bfs_path.pop(0)
                return next_dir
            else:
                self._bfs_path = []  # camino bloqueado, delega a BugNav

        return self.moveTo(c, self._explore_target, four_dirs)