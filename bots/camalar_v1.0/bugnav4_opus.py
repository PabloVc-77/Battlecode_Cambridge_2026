"""
BugNav4 Opus — basado en bugnav.py original, con fix de bucles.

Misma lógica de wall-following que bugnav.py (recalcula wallDir hacia el goal
cada turno → sigue el obstáculo pegado), pero con anti-loop:
  1. Visited states (pos + dir) → al detectar bucle cambia de mano (left↔right)
  2. Hard limit de pasos en wall-following
  3. Si ambas manos hacen loop → greedy step como último recurso

Interfaz 100% compatible:
    nav = BugNav()
    dir = nav.moveTo(c, goal, four_dirs=True)
    dir = nav.moveDvD(c, four_dirs=True)
"""

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import random


class BugNav:
    followingWall = False
    hitPoint = None
    wallDir = None
    visitedStates = set()
    start = None
    prevGoal = None

    # Anti-loop additions
    _use_left_hand = True      # True = rotate_left (como original), False = rotate_right
    _hand_switches = 0
    _MAX_HAND_SWITCHES = 2
    _wall_steps = 0
    _MAX_WALL_STEPS = 300

    def reset(self):
        self.followingWall = False
        self.hitPoint = None
        self.wallDir = None
        self.visitedStates.clear()
        self._wall_steps = 0

    def _switch_hand(self):
        """Cambia de mano (left↔right) y resetea los visited states."""
        self._use_left_hand = not self._use_left_hand
        self._hand_switches += 1
        self.visitedStates.clear()
        self._wall_steps = 0

    def moveTo(self, c: Controller, goal: Position, four_dirs: bool):
        current = c.get_position()

        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0
            self._use_left_hand = True

        # ── Fase directa: intentar moverse recto hacia el goal ──
        if not self.followingWall:
            nextDir = current.direction_to(goal)
            flag = False
            if four_dirs:
                (dx, dy) = nextDir.delta()
                if dx != 0 and dy != 0:
                    flag = True
                    nextDir = nextDir.rotate_left()

            if c.can_move(nextDir) or c.can_build_road(current.add(nextDir)):
                return nextDir
            elif four_dirs and flag:
                nextDir = nextDir.rotate_right().rotate_right()
                if c.can_move(nextDir) or c.can_build_road(current.add(nextDir)):
                    return nextDir

            # Hit obstacle → start wall following
            self.followingWall = True
            self.hitPoint = current
            self.wallDir = nextDir
            self.visitedStates.clear()
            self._wall_steps = 0

        # ── Wall-following ──
        c.draw_indicator_dot(current, 245, 63, 39)

        # Detección de bucle por estado (posición + dirección del muro)
        stateKey = (current.x, current.y, str(self.wallDir))
        if stateKey in self.visitedStates:
            # Bucle detectado → intentar cambiar de mano
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
                c.draw_indicator_dot(current, 63, 63, 245)  # azul = cambio de mano
            else:
                # Ambas manos fallaron → greedy step
                greedy = self._greedy_step(c, current, goal, four_dirs)
                if greedy != Direction.CENTRE:
                    self.reset()
                    self._hand_switches = 0
                    c.draw_indicator_dot(current, 245, 245, 39)  # amarillo = greedy
                    return greedy
                # Completamente stuck
                self.reset()
                self._hand_switches = 0
                return Direction.CENTRE

        self.visitedStates.add(stateKey)
        self._wall_steps += 1

        # Hard limit de pasos
        if self._wall_steps > self._MAX_WALL_STEPS:
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
            else:
                self.reset()
                self._hand_switches = 0
                return Direction.CENTRE

        # ── Seguir la pared (igual que bugnav.py pero con mano intercambiable) ──
        # Recalcular wallDir hacia el goal cada turno (esto es lo que hace
        # que siga el obstáculo pegado, como en el bugnav original)
        self.wallDir = current.direction_to(goal)
        nextDir = self.followWall(c, four_dirs=four_dirs)

        if nextDir == Direction.CENTRE:
            # No hay dirección válida
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
                return Direction.CENTRE
            self.reset()
            self._hand_switches = 0
            return Direction.CENTRE

        # Leave obstacle if back on M-line closer to goal
        nextPos = current.add(nextDir)
        if (self.onMline(nextPos, c) and
                nextPos.distance_squared(goal) < self.hitPoint.distance_squared(goal)):
            self.followingWall = False
            self.visitedStates.clear()
            self._wall_steps = 0
            self._hand_switches = 0

        return nextDir

    def followWall(self, c: Controller, four_dirs: bool):
        """
        Misma lógica que bugnav.py original, pero con mano intercambiable.
        - Left hand (original): rotate_left para buscar la primera dirección libre
        - Right hand: rotate_right
        """
        dir = self.wallDir
        current = c.get_position()

        rotate = Direction.rotate_left if self._use_left_hand else Direction.rotate_right

        for i in range(8):
            dir = rotate(dir)

            dx, dy = dir.delta()
            if four_dirs and dx != 0 and dy != 0:
                continue

            if c.can_move(dir) or c.can_build_road(current.add(dir)):
                self.wallDir = dir
                return dir

        return Direction.CENTRE

    def onMline(self, p: Position, c: Controller):
        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prevGoal))
        d3 = math.sqrt(self.start.distance_squared(self.prevGoal))

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)

        return abs((d1 + d2) - d3) < 0.5

    def _greedy_step(self, c: Controller, current: Position, goal: Position, four_dirs: bool):
        """Intenta moverse en la dirección que minimice distancia al goal."""
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

        # Si greedy no mejora, al menos mover a cualquier lado pasable
        if best_dir == Direction.CENTRE:
            for d in dirs_list:
                if c.can_move(d) or c.can_build_road(current.add(d)):
                    return d

        return best_dir

    dvd = None
    fdirs = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
    dirs = [Direction.NORTH, Direction.NORTHEAST, Direction.NORTHWEST, Direction.WEST,
            Direction.EAST, Direction.SOUTHEAST, Direction.SOUTH, Direction.SOUTHWEST]

    def moveDvD(self, c: Controller, four_dirs: bool):
        current = c.get_position()
        if self.dvd is None:
            self.dvd = random.choice(self.fdirs) if four_dirs else random.choice(self.dirs)

        if c.can_move(self.dvd) or c.can_build_road(current.add(self.dvd)):
            return self.dvd

        self.dvd = random.choice(self.fdirs) if four_dirs else random.choice(self.dirs)
        return self.dvd
