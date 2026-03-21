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

    if(nextPos.x >= 0 and nextPos.x < w and nextPos.y >= 0 and nextPos.y < h):
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

        # M-line tolerance — más amplia para cubrir pasos diagonales
        # Un paso diagonal sobre una línea recta puede desviarse hasta ~0.7
        self.mline_epsilon = 0.25

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

            flag = False
            if(four_dirs and _is_diagonal(dir_to_goal)):
                flag = True
                dir_to_goal = dir_to_goal.rotate_left()

            if _can_i_move(c, dir_to_goal):
                return dir_to_goal
            elif(flag):
                dir_to_goal = dir_to_goal.rotate_right().rotate_right()
                if _can_i_move(c, dir_to_goal):
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
                    if _can_i_move(c, d):
                        self.prevWallDir = d
                        return d
                d = d.rotate_right()
        else:
            d = dir.rotate_right().rotate_right()  # arranca 90° der
            for _ in range(7):
                if not (four_dirs and _is_diagonal(d)):
                    if _can_i_move(c, d):
                        self.prevWallDir = d
                        return d
                d = d.rotate_left()

        return Direction.CENTRE

    def _wall_priority(self, wall_dir: Direction, left_hand: bool) -> list:
        """
        Dado que la pared está en wall_dir, devuelve las direcciones
        ordenadas de más pegada a la pared a más alejada.
        Left-hand: gira preferentemente a la izquierda de la pared.
        Right-hand: gira preferentemente a la derecha.
        """
        # Diagonales "pegadas" a la pared (tocan wall_dir)
        diag_left  = wall_dir.rotate_left()   # 45° izq de la pared
        diag_right = wall_dir.rotate_right()  # 45° der de la pared

        # Perpendiculares (90° respecto a la pared)
        perp_left  = wall_dir.rotate_left().rotate_left()   # 90° izq
        perp_right = wall_dir.rotate_right().rotate_right() # 90° der

        # Diagonales de huida (135°)
        escape_left  = perp_left.rotate_left()   # 135° izq
        escape_right = perp_right.rotate_right() # 135° der

        # Opuesta (180°) — último recurso
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
        # Distancia perpendicular punto-recta (más robusta que d1+d2≈d3)
        sx, sy = self.start.x, self.start.y
        gx, gy = self.prevGoal.x, self.prevGoal.y
        px, py = p.x, p.y

        dx, dy = gx - sx, gy - sy
        length_sq = dx*dx + dy*dy
        if length_sq == 0:
            return p == self.start

        # Proyección escalar sobre la M-line
        t = ((px - sx)*dx + (py - sy)*dy) / length_sq
        # Punto más cercano en la línea
        closest_x = sx + t*dx
        closest_y = sy + t*dy

        dist_perp = math.sqrt((px - closest_x)**2 + (py - closest_y)**2)

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)
        return dist_perp < 0.6  # tolerancia perpendicular real

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
    # RANDOM MOVEMENT
    # ==========================
    dvd = None

    def moveDvD(self, c: Controller, four_dirs: bool):
        if self.dvd is None:
            self.dvd = random.choice(self.fdirs if four_dirs else self.dirs)

        if _can_i_move(c, self.dvd):
            return self.dvd

        self.dvd = random.choice(self.fdirs if four_dirs else self.dirs)
        return self.dvd