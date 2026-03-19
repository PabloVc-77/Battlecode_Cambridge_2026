from cambc import Controller, Direction, Position
import math
import random


class BugNav:
    def __init__(self):
        self.reset()

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
        self.mline_epsilon = 0.3

        # Anti-oscillation
        self.lastLeaveDist = float("inf")
        self.min_progress = 1

        # Directions
        self.fdirs = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
        self.dirs = [
            Direction.NORTH, Direction.NORTHEAST, Direction.NORTHWEST,
            Direction.WEST, Direction.EAST,
            Direction.SOUTHEAST, Direction.SOUTH, Direction.SOUTHWEST
        ]

    def reset(self):
        self.mode = "GOAL"   # GOAL or WALL
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

        # Reset if goal changed
        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0

        # ==========================
        # GO TO GOAL
        # ==========================
        if self.mode == "GOAL":
            dir_to_goal = current.direction_to(goal)

            # Direct move if possible
            if c.can_move(dir_to_goal) or c.can_build_road(current.add(dir_to_goal)):
                return dir_to_goal

            # Hit obstacle → start wall following
            self.mode = "WALL"
            self.hitPoint = current
            self.prevWallDir = dir_to_goal
            self.wall_steps = 0
            self.visitedStates.clear()

        # ==========================
        # FOLLOW WALL
        # ==========================
        c.draw_indicator_dot(current, 245, 63, 39)

        nextDir = self.followWall(c, four_dirs)
        nextPos = current.add(nextDir)

        # Loop detection
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

        # Leave condition (Bug2)
        if self.onMline(nextPos, c) and nextPos.distance_squared(goal) < self.hitPoint.distance_squared(goal):
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

        # Define relative directions based on hand rule
        if self._use_left_hand:
            check_dirs = [
                dir.rotate_left(),                     # hug wall
                dir,                                   # forward
                dir.rotate_right(),                    # slight turn away
                dir.rotate_right().rotate_right()      # turn around
            ]
        else:
            check_dirs = [
                dir.rotate_right(),
                dir,
                dir.rotate_left(),
                dir.rotate_left().rotate_left()
            ]

        for d in check_dirs:
            dx, dy = d.delta()
            if four_dirs and dx != 0 and dy != 0:
                continue

            if c.can_move(d) or c.can_build_road(current.add(d)):
                self.prevWallDir = d
                return d

        return Direction.CENTRE


    # ==========================
    # LEAVE CONDITION
    # ==========================
    def shouldLeaveWall(self, current, nextPos, goal, c: Controller):
        if not self.onMline(nextPos):
            return False

        # Must improve vs hit point
        if nextPos.distance_squared(goal) >= self.hitPoint.distance_squared(goal) - self.min_progress:
           return False

        # Prevent oscillation
        if nextPos.distance_squared(goal) >= self.lastLeaveDist:
           return False

        return True

    # ==========================
    # M-LINE CHECK
    # ==========================
    def onMline(self, p: Position, c: Controller):
        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prevGoal))
        d3 = math.sqrt(self.start.distance_squared(self.prevGoal))

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)

        return abs((d1 + d2) - d3) < 0.5

    # ==========================
    # GREEDY ESCAPE
    # ==========================
    def _greedy_step(self, c: Controller, current: Position, goal: Position, four_dirs: bool):
        dirs_list = self.fdirs if four_dirs else self.dirs

        best_dir = Direction.CENTRE
        best_dist = current.distance_squared(goal)

        for d in dirs_list:
            if c.can_move(d) or c.can_build_road(current.add(d)):
                npos = current.add(d)
                nd = npos.distance_squared(goal)
                if nd < best_dist:
                    best_dist = nd
                    best_dir = d

        if best_dir == Direction.CENTRE:
            for d in dirs_list:
                if c.can_move(d) or c.can_build_road(current.add(d)):
                    return d

        return best_dir

    # ==========================
    # RANDOM MOVEMENT
    # ==========================
    dvd = None

    def moveDvD(self, c: Controller, four_dirs: bool):
        current = c.get_position()

        if self.dvd is None:
            self.dvd = random.choice(self.fdirs if four_dirs else self.dirs)

        if c.can_move(self.dvd) or c.can_build_road(current.add(self.dvd)):
            return self.dvd

        self.dvd = random.choice(self.fdirs if four_dirs else self.dirs)
        return self.dvd