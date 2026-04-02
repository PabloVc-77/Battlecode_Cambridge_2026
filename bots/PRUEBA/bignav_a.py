"""
BugNav 3.0 — A* incremental multi-tick + BugNav mejorado

ARQUITECTURA:
─────────────
El A* se ejecuta en background, repartido entre ticks:
  - Cada tick se le asigna un presupuesto de CPU (CPU_BUDGET_US µs).
  - La comprobación se hace por tiempo real de CPU, no por nodos,
    usando c.get_cpu_time_elapsed() que devuelve µs consumidos en el tick.
  - Mientras A* no termina, BugNav mueve al bot (nunca se queda quieto).
  - Cuando A* termina, se usa su path; BugNav se descarta.
  - Si el bot avanza y el goal entra en visión, se hace un BFS rápido
    de un solo tick como shortcut (igual que en v2.1).

SALIDA DE PARED MEJORADA:
──────────────────────────
En vez de esperar a cruzar la M-line (Bug2 clásico), el bot sale del
wall-following en cuanto detecta que puede avanzar más hacia el goal
que la distancia a la que chocó (heurística de distancia directa).
Esto evita el recorrido excesivo de perímetro en laberintos.

PRESUPUESTO CPU:
────────────────
CPU_BUDGET_US = 1700 µs por tick (de los 2000 µs disponibles).
El A* comprueba c.get_cpu_time_elapsed() en cada iteración y para
en cuanto se supera el umbral, retomando en el siguiente tick.
Si el tick ya llegó con poco presupuesto (lógica previa costosa),
el A* simplemente no avanza ese tick y BugNav cubre el movimiento.
"""

from cambc import Controller, Direction, Position, EntityType
import math
import random

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CPU_BUDGET_US = 1700      # µs máximos por tick antes de ceder el control
BFS_MAX_NODES = 80        # BFS rápido cuando goal está en visión

_ALL_DIRS = [
    Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
    Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST,
]
_CARD_DIRS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0


def _in_bounds(pos: Position, w: int, h: int) -> bool:
    return 0 <= pos.x < w and 0 <= pos.y < h


def _can_move(c: Controller, d: Direction, w: int, h: int) -> bool:
    if d == Direction.CENTRE:
        return False
    nxt = c.get_position().add(d)
    if not _in_bounds(nxt, w, h):
        return False
    barrier = c.get_tile_building_id(nxt)
    if barrier is not None and c.get_entity_type(barrier) == EntityType.BARRIER and c.get_team(barrier) == c.get_team():
        return True
    return c.can_move(d) or c.is_tile_empty(nxt) or c.is_tile_passable(nxt)


def _passable(c: Controller, pos: Position) -> bool:
    return c.is_tile_passable(pos) or c.is_tile_empty(pos)

# ---------------------------------------------------------------------------
# BFS rápido (un solo tick, goal en visión)
# ---------------------------------------------------------------------------

def _bfs_in_vision(c: Controller, start: Position, goal: Position,
                   w: int, h: int, max_nodes: int = BFS_MAX_NODES) -> list:
    if start == goal:
        return []
    parent = {start: None}
    queue = [start]
    head = 0
    nodes = 0
    while head < len(queue) and nodes < max_nodes:
        pos = queue[head]; head += 1; nodes += 1
        for d in _ALL_DIRS:
            nb = pos.add(d)
            if nb in parent or not _in_bounds(nb, w, h):
                continue
            if not c.is_in_vision(nb) or not _passable(c, nb):
                continue
            parent[nb] = (pos, d)
            if nb == goal:
                path = []
                cur = nb
                while parent[cur] is not None:
                    prev, direction = parent[cur]
                    path.append(direction)
                    cur = prev
                path.reverse()
                return path
            queue.append(nb)
    return []

# ---------------------------------------------------------------------------
# Estado del A* incremental
# ---------------------------------------------------------------------------

class AStarState:
    """
    Encapsula el estado completo de un A* en curso.
    open_list: lista de [f, g, pos] — búsqueda lineal del mínimo en cada tick.
    Para presupuestos pequeños, la lista crece despacio y la búsqueda lineal
    es más barata que mantener un heap con heapq en Python puro
    (heapq.heappush/pop tienen overhead de comparaciones en objetos complejos).
    """
    __slots__ = ("goal", "open_list", "g_best", "parent", "done", "path")

    def __init__(self, start: Position, goal: Position):
        self.goal = goal
        h = math.sqrt(start.distance_squared(goal))
        self.open_list = [[h, 0.0, start]]
        self.g_best = {start: 0.0}
        self.parent = {start: None}
        self.done = False
        self.path = []

    def is_active(self) -> bool:
        return not self.done and len(self.open_list) > 0

# ---------------------------------------------------------------------------
# A* incremental: consume CPU hasta CPU_BUDGET_US µs y luego cede
# ---------------------------------------------------------------------------

def _astar_tick(state: AStarState, c: Controller, w: int, h: int) -> None:
    """
    Avanza el A* mientras quede presupuesto de CPU en el tick actual.
    Comprueba c.get_cpu_time_elapsed() en cada iteración; si supera
    CPU_BUDGET_US, devuelve el control sin marcar done, para reanudar
    en el siguiente tick. BugNav cubre el movimiento mientras tanto.
    """
    if state.done:
        return

    ol = state.open_list
    g_best = state.g_best
    parent = state.parent
    goal = state.goal

    while ol:
        # Ceder si el tick ya consumió demasiada CPU
        if c.get_cpu_time_elapsed() >= CPU_BUDGET_US:
            return

        # Buscar el de menor f (búsqueda lineal — barata para listas pequeñas)
        best_idx = 0
        best_f = ol[0][0]
        for i in range(1, len(ol)):
            if ol[i][0] < best_f:
                best_f = ol[i][0]
                best_idx = i

        # Swap con el último para que pop() sea O(1)
        ol[best_idx], ol[-1] = ol[-1], ol[best_idx]
        f, g, pos = ol.pop()

        # Nodo obsoleto (g superado)
        if g > g_best.get(pos, float("inf")) + 1e-6:
            continue

        if pos == goal:
            path = []
            cur = pos
            while parent[cur] is not None:
                prev, direction = parent[cur]
                path.append(direction)
                cur = prev
            path.reverse()
            state.path = path
            state.done = True
            return

        for d in _ALL_DIRS:
            nb = pos.add(d)
            if not _in_bounds(nb, w, h):
                continue
            if not c.is_in_vision(nb) or not _passable(c, nb):
                continue
            step = 1.414 if _is_diagonal(d) else 1.0
            ng = g + step
            if ng >= g_best.get(nb, float("inf")):
                continue
            g_best[nb] = ng
            parent[nb] = (pos, d)
            h_val = math.sqrt(nb.distance_squared(goal))
            ol.append([ng + h_val, ng, nb])

    # open_list vacía: goal inalcanzable con la visión actual
    state.done = True

# ---------------------------------------------------------------------------
# BugNav 3.0
# ---------------------------------------------------------------------------

class BugNav:
    def __init__(self):
        # Estado moveTo
        self.prevGoal: Position | None = None
        self.start: Position | None = None
        self.mode = "GOAL"

        # A* incremental
        self._astar: AStarState | None = None
        self._path: list = []

        # BFS rápido (goal en visión)
        self._bfs_path: list = []

        # Wall following
        self._use_left_hand = True
        self._hand_switches = 0
        self._MAX_HAND_SWITCHES = 3

        self.hitPoint: Position | None = None
        self.hitDist: int = 10**9
        self.prevWallDir = Direction.CENTRE
        self.visitedStates: set = set()
        self.wall_steps = 0
        self.max_wall_steps = 300

        # M-line
        self.mline_epsilon = 1.5

        # Exploración
        self._visited: set = set()
        self._frontiers: set = set()
        self._explore_target: Position | None = None
        self._MAX_VISITED = 1500
        self._bfs_path_explore: list = []

        # DVD fallback
        self.dvd: Direction | None = None

        # Compatibilidad con código existente
        self.fdirs = _CARD_DIRS
        self.dirs = _ALL_DIRS

        # Cache dimensiones
        self._w = 0
        self._h = 0

    # -------------------------------------------------------------------------
    def _init_dims(self, c: Controller):
        if self._w == 0:
            self._w = c.get_map_width()
            self._h = c.get_map_height()

    def reset(self):
        self.mode = "GOAL"
        self.hitPoint = None
        self.hitDist = 10**9
        self.prevWallDir = Direction.CENTRE
        self.visitedStates.clear()
        self.wall_steps = 0

    def _full_reset(self):
        self.reset()
        self._astar = None
        self._path = []
        self._bfs_path = []
        self._hand_switches = 0

    def _switch_hand(self):
        self._use_left_hand = not self._use_left_hand
        self._hand_switches += 1
        self.visitedStates.clear()
        self.wall_steps = 0

    # -------------------------------------------------------------------------
    def is_reachable(self, c: Controller, goal: Position) -> bool:
        self._init_dims(c)
        current = c.get_position()
        if current == goal:
            return True
        w, h = self._w, self._h
        visited = {current}
        queue = [current]
        head = 0
        nodes = 0
        while head < len(queue) and nodes < 150:
            pos = queue[head]; head += 1; nodes += 1
            for d in _ALL_DIRS:
                nb = pos.add(d)
                if (nb not in visited and _in_bounds(nb, w, h)
                        and c.is_in_vision(nb) and _passable(c, nb)):
                    if nb == goal:
                        return True
                    visited.add(nb)
                    queue.append(nb)
        return False

    # =========================================================================
    # MOVE TO
    # =========================================================================
    def moveTo(self, c: Controller, goal: Position, four_dirs: bool) -> Direction:
        self._init_dims(c)
        current = c.get_position()
        w, h = self._w, self._h

        if goal != self.prevGoal:
            self._full_reset()
            self.start = current
            self.prevGoal = goal

        # ── 1. BFS rápido si el goal ya está en visión ───────────────────────
        if c.is_in_vision(goal):
            if self._bfs_path and not _can_move(c, self._bfs_path[0], w, h):
                self._bfs_path = []
            if not self._bfs_path:
                self._bfs_path = _bfs_in_vision(c, current, goal, w, h)
                if self._bfs_path:
                    self._astar = None
                    self._path = []
            if self._bfs_path:
                return self._consume_path(c, self._bfs_path, four_dirs, w, h)
        else:
            self._bfs_path = []

        # ── 2. A* incremental en background ──────────────────────────────────
        if self._astar is None and not self._path:
            self._astar = AStarState(current, goal)

        if self._astar is not None and self._astar.is_active():
            _astar_tick(self._astar, c, w, h)
            if self._astar.done:
                if self._astar.path:
                    self._path = self._trim_path(current, self._astar.path)
                self._astar = None

        if self._path:
            if not _can_move(c, self._path[0], w, h):
                # Path bloqueado por cambio de mapa — reiniciar A*
                self._astar = AStarState(current, goal)
                self._path = []
            else:
                return self._consume_path(c, self._path, four_dirs, w, h)

        # ── 3. BugNav mientras A* calcula (garantía de movimiento) ───────────
        # BugNav siempre devuelve una dirección válida; si está en modo GOAL y
        # no puede avanzar directo, entra en wall-following. El A* continúa en
        # background y reemplaza a BugNav en cuanto termina.
        return self._bugnav_step(c, goal, four_dirs)

    def _consume_path(self, c: Controller, path: list,
                      four_dirs: bool, w: int, h: int) -> Direction:
        current = c.get_position()
        nxt = path[0]
        if four_dirs and _is_diagonal(nxt):
            for alt in (nxt.rotate_left(), nxt.rotate_right()):
                if _can_move(c, alt, w, h):
                    path.clear()
                    return alt
            path.clear()
            return self._bugnav_step(c, self.prevGoal, four_dirs)
        if _can_move(c, nxt, w, h):
            path.pop(0)
            c.draw_indicator_line(current, current.add(nxt), 245, 39, 245)
            return nxt
        # Dirección bloqueada: descarta el path y BugNav cubre este tick
        path.clear()
        return self._bugnav_step(c, self.prevGoal, four_dirs)

    def _trim_path(self, current: Position, path: list) -> list:
        """
        El A* calculó el path desde self.start. Si BugNav ya avanzó al bot,
        simula el avance para descartar los pasos ya ejecutados.
        """
        if not path or self.start is None:
            return path
        pos = self.start
        i = 0
        while i < len(path) and pos != current:
            pos = pos.add(path[i])
            i += 1
        return path[i:] if pos == current else path

    # =========================================================================
    # Bug2 mejorado
    # =========================================================================
    def _bugnav_step(self, c: Controller, goal: Position, four_dirs: bool) -> Direction:
        current = c.get_position()
        w, h = self._w, self._h

        if self.mode == "GOAL":
            dir_to_goal = current.direction_to(goal)
            if four_dirs and _is_diagonal(dir_to_goal):
                dl, dr = dir_to_goal.rotate_left(), dir_to_goal.rotate_right()
                if _can_move(c, dl, w, h): return dl
                if _can_move(c, dr, w, h): return dr
            else:
                if _can_move(c, dir_to_goal, w, h):
                    return dir_to_goal

            self.mode = "WALL"
            self.hitPoint = current
            self.hitDist = current.distance_squared(goal)
            self.prevWallDir = self._cardinal_towards(current, goal)
            self.wall_steps = 0
            self.visitedStates.clear()

        # WALL
        c.draw_indicator_dot(current, 245, 63, 39)
        next_dir = self._follow_wall(c, four_dirs, w, h)

        # ── Fallback: si follow_wall no encuentra nada, moverse a cualquier
        #    dirección libre para no quedarse quieto ──────────────────────────
        if next_dir == Direction.CENTRE:
            next_dir = self._any_free_dir(c, four_dirs, w, h)
            if next_dir != Direction.CENTRE:
                self.prevWallDir = next_dir
            return next_dir

        next_pos = current.add(next_dir)

        state_key = (current.x, current.y, next_dir.value)
        if state_key in self.visitedStates:
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
                self.hitDist = current.distance_squared(goal)
            else:
                result = self._greedy_step(c, current, goal, four_dirs, w, h)
                self.reset()
                self._hand_switches = 0
                return result

        self.visitedStates.add(state_key)
        self.wall_steps += 1
        if self.wall_steps > self.max_wall_steps:
            result = self._greedy_step(c, current, goal, four_dirs, w, h)
            self.reset()
            return result

        # ── Salida de pared mejorada ─────────────────────────────────────────
        # Condición A (Bug2): en M-line y más cerca que en el hitPoint
        next_dist = (next_pos.distance_squared(goal)
                     if next_dir != Direction.CENTRE else 10**9)
        can_exit = (next_dir != Direction.CENTRE
                    and next_dist < self.hitDist
                    and self._on_mline(next_pos, c))

        # Condición B (nueva): desde la pared, hay una dirección libre que nos
        # acerca más al goal que hitDist. Permite salir en corredores paralelos
        # sin esperar a cruzar la M-line.
        if not can_exit and next_dir != Direction.CENTRE:
            dir_to_goal = current.direction_to(goal)
            candidates = ([dir_to_goal] if not _is_diagonal(dir_to_goal)
                          else [dir_to_goal.rotate_left(), dir_to_goal.rotate_right()])
            for d_try in candidates:
                if (_can_move(c, d_try, w, h)
                        and current.add(d_try).distance_squared(goal) < self.hitDist):
                    can_exit = True
                    next_dir = d_try
                    break

        if can_exit:
            self.mode = "GOAL"
            self.visitedStates.clear()
            self.hitDist = next_pos.distance_squared(goal)

        return next_dir

    def _follow_wall(self, c: Controller, four_dirs: bool, w: int, h: int) -> Direction:
        if self.prevWallDir == Direction.CENTRE:
            return Direction.CENTRE
        d = self.prevWallDir
        if self._use_left_hand:
            start_d = d.rotate_left().rotate_left()
            for _ in range(8):
                if not (four_dirs and _is_diagonal(start_d)):
                    if _can_move(c, start_d, w, h):
                        self.prevWallDir = start_d
                        return start_d
                start_d = start_d.rotate_right()
        else:
            start_d = d.rotate_right().rotate_right()
            for _ in range(8):
                if not (four_dirs and _is_diagonal(start_d)):
                    if _can_move(c, start_d, w, h):
                        self.prevWallDir = start_d
                        return start_d
                start_d = start_d.rotate_left()
        return Direction.CENTRE

    def _any_free_dir(self, c: Controller, four_dirs: bool, w: int, h: int) -> Direction:
        """Devuelve cualquier dirección transitable. Garantía de no quedarse quieto."""
        dirs_list = _CARD_DIRS if four_dirs else _ALL_DIRS
        for d in dirs_list:
            if _can_move(c, d, w, h):
                return d
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
        dist_perp = math.sqrt((px - (sx + t*dx))**2 + (py - (sy + t*dy))**2)
        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)
        return dist_perp < self.mline_epsilon

    def _greedy_step(self, c: Controller, current: Position,
                     goal: Position, four_dirs: bool, w: int, h: int) -> Direction:
        dirs_list = _CARD_DIRS if four_dirs else _ALL_DIRS
        best_dir = Direction.CENTRE
        best_dist = current.distance_squared(goal)
        for d in dirs_list:
            if _can_move(c, d, w, h):
                nd = current.add(d).distance_squared(goal)
                if nd < best_dist:
                    best_dist = nd
                    best_dir = d
        if best_dir == Direction.CENTRE:
            # No hay mejora posible: moverse a cualquier dirección libre
            return self._any_free_dir(c, four_dirs, w, h)
        return best_dir

    # =========================================================================
    # DVD
    # =========================================================================
    def moveDvD(self, c: Controller, four_dirs: bool) -> Direction:
        self._init_dims(c)
        w, h = self._w, self._h
        dirs_list = _CARD_DIRS if four_dirs else _ALL_DIRS
        if self.dvd is None:
            self.dvd = random.choice(dirs_list)
        if _can_move(c, self.dvd, w, h):
            return self.dvd
        self.dvd = random.choice(dirs_list)
        return self.dvd

    # =========================================================================
    # Exploración
    # =========================================================================
    def _update_exploration(self, c: Controller):
        w, h = self._w, self._h
        for pos in c.get_nearby_tiles():
            if pos not in self._visited:
                self._visited.add(pos)
                self._frontiers.discard(pos)
                for d in _ALL_DIRS:
                    nb = pos.add(d)
                    if (0 <= nb.x < w and 0 <= nb.y < h
                            and nb not in self._visited
                            and c.is_in_vision(nb) and _passable(c, nb)):
                        self._frontiers.add(nb)
        if len(self._visited) > self._MAX_VISITED:
            current = c.get_position()
            sorted_v = sorted(self._visited, key=lambda p: current.distance_squared(p))
            self._visited = set(sorted_v[:self._MAX_VISITED // 2])

    def _pick_explore_target(self, c: Controller) -> Position | None:
        if not self._frontiers:
            return None
        current = c.get_position()
        return min(self._frontiers, key=lambda p: current.distance_squared(p))

    def moveExplore(self, c: Controller, four_dirs: bool = False) -> Direction:
        self._init_dims(c)
        self._update_exploration(c)
        current = c.get_position()
        w, h = self._w, self._h

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

        if c.is_in_vision(goal):
            if self._bfs_path_explore and not _can_move(c, self._bfs_path_explore[0], w, h):
                self._bfs_path_explore = []
            if not self._bfs_path_explore:
                self._bfs_path_explore = _bfs_in_vision(c, current, goal, w, h)
            if self._bfs_path_explore:
                nxt = self._bfs_path_explore[0]
                if _can_move(c, nxt, w, h):
                    self._bfs_path_explore.pop(0)
                    return nxt
                self._bfs_path_explore = []
        else:
            self._bfs_path_explore = []

        if goal != self.prevGoal:
            self._full_reset()
            self.start = current
            self.prevGoal = goal

        return self._bugnav_step(c, goal, four_dirs)