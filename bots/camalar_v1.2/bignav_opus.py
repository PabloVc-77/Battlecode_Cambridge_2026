from cambc import Controller, Direction, Position
import math
import random


def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0


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

        # M-line tolerance — más amplia para cubrir pasos diagonales
        # Un paso diagonal sobre una línea recta puede desviarse hasta ~0.7
        self.mline_epsilon = 0.5

        # Anti-oscillation
        self.lastLeaveDist = float("inf")

        # Directions
        self.fdirs = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
        self.dirs = [
            Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
            Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
        ]

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

        # ==========================
        # GO TO GOAL
        # ==========================
        if self.mode == "GOAL":
            dir_to_goal = current.direction_to(goal)

            if c.can_move(dir_to_goal) or c.can_build_road(current.add(dir_to_goal)):
                return dir_to_goal

            # Chocamos → iniciar wall following
            self.mode = "WALL"
            self.hitPoint = current
            self.lastLeaveDist = current.distance_squared(goal)
            # Si four_dirs, aseguramos que prevWallDir no sea diagonal
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

        # ── Condición de salida Bug2 ──────────────────────────────────────
        # Usamos shouldLeaveWall (que antes no se llamaba nunca)
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

        # Construye la lista de 7 candidatos (dejamos fuera la dirección
        # completamente opuesta para no retroceder innecesariamente).
        #
        # Left-hand rule:  arrancamos 2 giros a la izquierda (90°) y
        #                  rotamos hacia la derecha paso a paso (CW).
        # Right-hand rule: arrancamos 2 giros a la derecha (90°) y
        #                  rotamos hacia la izquierda paso a paso (CCW).
        #
        # Con rotate_left/rotate_right = 45°, 7 pasos cubren 315°,
        # es decir todas las direcciones excepto la opuesta.

        if self._use_left_hand:
            d = dir.rotate_left().rotate_left()   # arranca 90° izq
            for _ in range(7):
                if not (four_dirs and _is_diagonal(d)):
                    if c.can_move(d) or c.can_build_road(current.add(d)):
                        self.prevWallDir = d
                        return d
                d = d.rotate_right()
        else:
            d = dir.rotate_right().rotate_right()  # arranca 90° der
            for _ in range(7):
                if not (four_dirs and _is_diagonal(d)):
                    if c.can_move(d) or c.can_build_road(current.add(d)):
                        self.prevWallDir = d
                        return d
                d = d.rotate_left()

        return Direction.CENTRE

    # ==========================
    # LEAVE CONDITION (Bug2)  ← ahora sí se usa
    # ==========================
    def shouldLeaveWall(self, current: Position, nextPos: Position,
                        goal: Position, c: Controller) -> bool:
        # 1. nextPos debe estar sobre (o cerca de) la M-line
        if not self.onMline(nextPos, c):
            return False

        # 2. Debe estar más cerca del objetivo que el hitPoint
        if nextPos.distance_squared(goal) >= self.hitPoint.distance_squared(goal):
            return False

        # 3. Anti-oscilación: no debe ser peor que la última salida
        if nextPos.distance_squared(goal) >= self.lastLeaveDist:
            return False

        return True

    # ==========================
    # M-LINE CHECK  ← tolerancia ajustada para diagonales
    # ==========================
    def onMline(self, p: Position, c: Controller) -> bool:
        if self.start is None or self.prevGoal is None:
            return False

        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prevGoal))
        d3 = math.sqrt(self.start.distance_squared(self.prevGoal))

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)

        return abs((d1 + d2) - d3) < self.mline_epsilon

    # ==========================
    # GREEDY ESCAPE
    # ==========================
    def _greedy_step(self, c: Controller, current: Position,
                     goal: Position, four_dirs: bool):
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