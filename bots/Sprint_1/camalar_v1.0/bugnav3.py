from cambc import Controller, Direction, EntityType, Environment, Position
import math
import random


class BugNav:
    """
    Bug2 con soporte 4/8 direcciones.
    El wall-following usa regla de mano izquierda correcta:
    empieza desde rotate_right para intentar doblar esquinas primero.
    """

    def __init__(self):
        self.following_wall = False
        self.hit_point: Position = None
        self.wall_dir: Direction = None
        self.visited_states: set = set()
        self.start: Position = None
        self.prev_goal: Position = None
        self.dvd: Direction = None
        self._wall_steps = 0
        self._MAX_WALL_STEPS = 200  # safety net anti-bucle absoluto

    # ─────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────

    def moveTo(self, c: Controller, goal: Position, four_dirs: bool = True) -> Direction:
        current = c.get_position()

        if goal != self.prev_goal:
            self._reset()
            self.start = current
            self.prev_goal = goal

        # ── Fase 1: movimiento directo ──────────────────────────────────────
        if not self.following_wall:
            for d in self._dirs_toward_goal(current, goal, four_dirs):
                if self._can_pass(c, current, d):
                    return d

            # Todas las candidatas bloqueadas → wall-following
            self.following_wall = True
            self.hit_point = current
            self.wall_dir = self._dirs_toward_goal(current, goal, four_dirs)[0]
            self.visited_states.clear()
            self._wall_steps = 0
            c.draw_indicator_dot(current, 245, 63, 39)

        # ── Fase 2: wall-following ──────────────────────────────────────────
        self._wall_steps += 1

        # Detección de bucle por estado repetido
        state_key = (current.x, current.y, self.wall_dir.delta())
        if state_key in self.visited_states or self._wall_steps > self._MAX_WALL_STEPS:
            c.draw_indicator_dot(current, 200, 0, 0)
            self._reset()
            return Direction.CENTRE
        self.visited_states.add(state_key)

        next_dir = self._follow_wall(c, four_dirs)
        if next_dir == Direction.CENTRE:
            self._reset()
            return Direction.CENTRE

        # Salida: sobre la M-line y más cerca de la meta que el hitPoint
        next_pos = current.add(next_dir)
        if (self._on_mline(next_pos, c) and
                next_pos.distance_squared(goal) < self.hit_point.distance_squared(goal)):
            self.following_wall = False
            self.visited_states.clear()
            self._wall_steps = 0

        c.draw_indicator_dot(current, 245, 140, 39)
        return next_dir

    def moveDvD(self, c: Controller, four_dirs: bool = True) -> Direction:
        current = c.get_position()
        pool = self._FOUR_DIRS if four_dirs else self._ALL_DIRS
        if self.dvd is None:
            self.dvd = random.choice(pool)
        if self._can_pass(c, current, self.dvd):
            return self.dvd
        self.dvd = random.choice(pool)
        return self.dvd

    # ─────────────────────────────────────────────
    # Internos
    # ─────────────────────────────────────────────

    _FOUR_DIRS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
    _ALL_DIRS  = [
        Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
        Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
    ]

    def _reset(self):
        self.following_wall = False
        self.hit_point = None
        self.wall_dir = None
        self.visited_states.clear()
        self._wall_steps = 0

    def _can_pass(self, c: Controller, pos: Position, d: Direction) -> bool:
        return c.can_move(d) or c.can_build_road(pos.add(d))

    def _dirs_toward_goal(self, current: Position, goal: Position, four_dirs: bool) -> list:
        """
        Candidatas ordenadas hacia la meta.
        4-dirs: descompone diagonal en sus 2 cardinales (eje mayor primero).
        8-dirs: ideal + adyacentes para evitar wall-following por obstáculos pequeños.
        """
        d = current.direction_to(goal)

        if not four_dirs:
            return [d, d.rotate_left(), d.rotate_right()]

        dx, dy = d.delta()
        if dx == 0 or dy == 0:
            return [d]

        d_a = d.rotate_right()  # un cardinal
        d_b = d.rotate_left()   # el otro cardinal
        gx = abs(goal.x - current.x)
        gy = abs(goal.y - current.y)

        if gx >= gy:
            # preferir eje horizontal
            return ([d_a, d_b] if d_a.delta()[0] != 0 else [d_b, d_a])
        else:
            # preferir eje vertical
            return ([d_a, d_b] if d_a.delta()[1] != 0 else [d_b, d_a])

    def _follow_wall(self, c: Controller, four_dirs: bool) -> Direction:
        """
        Regla de mano izquierda correcta.

        CLAVE: empezamos desde wall_dir.rotate_right()
        Esto hace que el robot intente primero "doblar la esquina" (hugging),
        luego continuar recto, luego girar a la izquierda.

        Ejemplo con wall_dir=WEST (acabo de moverme al oeste):
          4-dirs prueba en orden: NORTH → WEST → SOUTH → EAST
          ↑ correcto: intenta ir al norte (doblar esquina) antes que continuar oeste

        Con wall_dir=WEST y empezando desde wall_dir (bug anterior):
          4-dirs prueba: SOUTH → EAST → NORTH
          ↑ incorrecto: huye del muro hacia el sur primero
        """
        current = c.get_position()
        # ← CORRECCIÓN PRINCIPAL: rotate_right, no wall_dir directamente
        d = self.wall_dir.rotate_right()

        for _ in range(8):
            dx, dy = d.delta()
            if four_dirs and dx != 0 and dy != 0:
                d = d.rotate_left()
                continue
            if self._can_pass(c, current, d):
                self.wall_dir = d  # actualizar para el próximo frame
                return d
            d = d.rotate_left()

        return Direction.CENTRE

    def _on_mline(self, p: Position, c: Controller) -> bool:
        if self.start is None or self.prev_goal is None:
            return False
        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prev_goal))
        d3 = math.sqrt(self.start.distance_squared(self.prev_goal))
        c.draw_indicator_line(self.start, self.prev_goal, 228, 245, 39)
        return abs((d1 + d2) - d3) < 0.5


# Constante de uso
FourDirs = True