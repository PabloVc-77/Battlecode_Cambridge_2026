"""
BugNav 2.1 — optimizado para el límite de 2ms por tick

Estrategia de coste:
- BFS ligero (con dict de padres, sin copiar listas) SOLO cuando el goal
  está dentro del radio de visión. Se recalcula solo cuando el path se invalida.
- BugNav Bug2 como fallback cuando el goal no es visible o el BFS falla.
- M-line con umbral ampliado (1.5) y restricción t∈[0,1].
- Condición de salida de muro simplificada: sale cuando está más cerca
  del hitPoint sin depender de lastLeaveDist.
- Paths separados para moveTo y moveExplore.
- moveExplore no descarta el target al verlo, solo al llegar.
- Límite de memoria en _visited.
"""

from cambc import Controller, Direction, Position
import math
import random

# ---------------------------------------------------------------------------
# Helpers globales (sin acceso a self → más rápidos como funciones libres)
# ---------------------------------------------------------------------------

def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0


def _in_bounds(pos: Position, w: int, h: int) -> bool:
    return 0 <= pos.x < w and 0 <= pos.y < h


def _can_move(c: Controller, d: Direction, w: int, h: int) -> bool:
    """True si el bot puede (o podrá pronto) ocupar la casilla en dirección d."""
    if d == Direction.CENTRE:
        return False
    nxt = c.get_position().add(d)
    if not _in_bounds(nxt, w, h):
        return False
    return c.can_move(d) or c.is_tile_empty(nxt) or c.is_tile_passable(nxt)


_ALL_DIRS = [
    Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
    Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST,
]
_CARD_DIRS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]


# ---------------------------------------------------------------------------
# BFS ligero: reconstruye el path con dict de padres (sin copiar listas)
# Solo se llama cuando el goal está en visión.
# max_nodes controla el presupuesto CPU; con 80-100 nodos es suficiente para
# el radio de visión del builder bot (r²=20, ~60 tiles en área).
# ---------------------------------------------------------------------------

def _bfs_in_vision(c: Controller, start: Position, goal: Position,
                   w: int, h: int, max_nodes: int = 80) -> list:
    """
    BFS desde start hasta goal usando solo tiles visibles y transitables.
    Devuelve lista de Direction. Devuelve [] si no hay camino o se agota max_nodes.
    Reconstruye el path con un dict para evitar copias de lista por nodo.
    """
    if start == goal:
        return []

    parent = {start: None}   # pos -> (pos_anterior, direction)
    queue = [start]
    head = 0
    nodes = 0

    while head < len(queue) and nodes < max_nodes:
        pos = queue[head]
        head += 1
        nodes += 1

        for d in _ALL_DIRS:
            nb = pos.add(d)
            if nb in parent:
                continue
            if not _in_bounds(nb, w, h):
                continue
            if not c.is_in_vision(nb):
                continue
            if not (c.is_tile_passable(nb) or c.is_tile_empty(nb)):
                continue
            parent[nb] = (pos, d)
            if nb == goal:
                # Reconstruir path hacia atrás
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
# BugNav 2.1
# ---------------------------------------------------------------------------

class BugNav:
    def __init__(self):
        # Estado moveTo
        self.prevGoal: Position | None = None
        self.start: Position | None = None
        self.mode = "GOAL"           # "GOAL" | "WALL"

        # Wall following
        self._use_left_hand = True
        self._hand_switches = 0
        self._MAX_HAND_SWITCHES = 3

        self.hitPoint: Position | None = None
        self.hitDist: int = 10**9   # dist² al goal en el momento del choque
        self.prevWallDir = Direction.CENTRE
        self.visitedStates: set = set()
        self.wall_steps = 0
        self.max_wall_steps = 300

        # M-line (umbral ampliado respecto al original)
        self.mline_epsilon = 1.5

        # BFS paths — separados para no interferir entre moveTo y explore
        self._bfs_path_to: list = []
        self._bfs_path_explore: list = []

        # Exploración
        self._visited: set = set()
        self._frontiers: set = set()
        self._explore_target: Position | None = None
        self._MAX_VISITED = 1500

        # DVD fallback
        self.dvd: Direction | None = None

        # Aliases para compatibilidad con código existente
        self.fdirs = _CARD_DIRS
        self.dirs = _ALL_DIRS

        # Cache de dimensiones (se inicializa en el primer tick)
        self._w: int = 0
        self._h: int = 0

    # -----------------------------------------------------------------------
    def _init_dims(self, c: Controller):
        """Cachea las dimensiones del mapa la primera vez."""
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

    def _switch_hand(self):
        self._use_left_hand = not self._use_left_hand
        self._hand_switches += 1
        self.visitedStates.clear()
        self.wall_steps = 0

    # -----------------------------------------------------------------------
    # Reachability (BFS sin guardar path, límite conservador)
    # -----------------------------------------------------------------------
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
            pos = queue[head]
            head += 1
            nodes += 1
            for d in _ALL_DIRS:
                nb = pos.add(d)
                if (nb not in visited
                        and _in_bounds(nb, w, h)
                        and c.is_in_vision(nb)
                        and (c.is_tile_passable(nb) or c.is_tile_empty(nb))):
                    if nb == goal:
                        return True
                    visited.add(nb)
                    queue.append(nb)
        return False

    # -----------------------------------------------------------------------
    # MOVE TO (entrada principal)
    # -----------------------------------------------------------------------
    def moveTo(self, c: Controller, goal: Position, four_dirs: bool) -> Direction:
        self._init_dims(c)
        current = c.get_position()
        w, h = self._w, self._h

        # Resetear estado si el objetivo cambió
        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0
            self._bfs_path_to = []

        # ── BFS ligero: solo si el goal está en visión ──────────────────────
        # Recalcular si el path está vacío O si el siguiente paso quedó bloqueado
        if c.is_in_vision(goal):
            if self._bfs_path_to and not _can_move(c, self._bfs_path_to[0], w, h):
                self._bfs_path_to = []

            if not self._bfs_path_to:
                self._bfs_path_to = _bfs_in_vision(c, current, goal, w, h, max_nodes=80)

            if self._bfs_path_to:
                nxt = self._bfs_path_to[0]

                # Adaptar diagonal a four_dirs si hace falta
                if four_dirs and _is_diagonal(nxt):
                    alt = nxt.rotate_left()
                    if _can_move(c, alt, w, h):
                        self._bfs_path_to = []   # invalidar; recalculará
                        return alt
                    alt = nxt.rotate_right()
                    if _can_move(c, alt, w, h):
                        self._bfs_path_to = []
                        return alt
                    self._bfs_path_to = []       # sin alternativa → BugNav
                else:
                    if _can_move(c, nxt, w, h):
                        self._bfs_path_to.pop(0)
                        c.draw_indicator_line(current, current.add(nxt), 245, 39, 245)
                        return nxt
                    else:
                        self._bfs_path_to = []   # bloqueado → recalcular
        else:
            # Goal fuera de visión: invalidar cualquier path antiguo
            self._bfs_path_to = []

        # ── BugNav como fallback ────────────────────────────────────────────
        return self._bugnav_step(c, goal, four_dirs)

    # -----------------------------------------------------------------------
    # Núcleo Bug2
    # -----------------------------------------------------------------------
    def _bugnav_step(self, c: Controller, goal: Position, four_dirs: bool) -> Direction:
        current = c.get_position()
        w, h = self._w, self._h

        if self.mode == "GOAL":
            dir_to_goal = current.direction_to(goal)

            if four_dirs and _is_diagonal(dir_to_goal):
                dl = dir_to_goal.rotate_left()
                dr = dir_to_goal.rotate_right()
                if _can_move(c, dl, w, h):
                    return dl
                if _can_move(c, dr, w, h):
                    return dr
            else:
                if _can_move(c, dir_to_goal, w, h):
                    return dir_to_goal

            # Choque → iniciar wall following
            self.mode = "WALL"
            self.hitPoint = current
            self.hitDist = current.distance_squared(goal)
            self.prevWallDir = self._cardinal_towards(current, goal)
            self.wall_steps = 0
            self.visitedStates.clear()

        # ── WALL mode ────────────────────────────────────────────────────────
        c.draw_indicator_dot(current, 245, 63, 39)
        next_dir = self._follow_wall(c, four_dirs, w, h)
        next_pos = current.add(next_dir)

        # Detección de bucle por estado (posición + dirección)
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

        # Anti-stuck timeout
        self.wall_steps += 1
        if self.wall_steps > self.max_wall_steps:
            result = self._greedy_step(c, current, goal, four_dirs, w, h)
            self.reset()
            return result

        # Condición de salida Bug2:
        # Salir si estamos en la M-line Y más cerca del goal que en el hitPoint
        if (next_dir != Direction.CENTRE
                and self._on_mline(next_pos, c)
                and next_pos.distance_squared(goal) < self.hitDist):
            self.mode = "GOAL"
            self.visitedStates.clear()
            self.hitDist = next_pos.distance_squared(goal)

        return next_dir

    # -----------------------------------------------------------------------
    # Wall following
    # -----------------------------------------------------------------------
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

    def _cardinal_towards(self, pos: Position, goal: Position) -> Direction:
        """Dirección cardinal dominante sin diagonal."""
        dx = goal.x - pos.x
        dy = goal.y - pos.y
        if abs(dx) >= abs(dy):
            return Direction.EAST if dx > 0 else Direction.WEST
        return Direction.SOUTH if dy > 0 else Direction.NORTH

    # -----------------------------------------------------------------------
    # M-line mejorada
    # -----------------------------------------------------------------------
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
        # Solo válida en el segmento start→goal
        if t < 0.0 or t > 1.0:
            return False

        cx_ = sx + t * dx
        cy_ = sy + t * dy
        dist_perp = math.sqrt((px - cx_) ** 2 + (py - cy_) ** 2)

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)
        return dist_perp < self.mline_epsilon

    # -----------------------------------------------------------------------
    # Greedy fallback (último recurso)
    # -----------------------------------------------------------------------
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
            for d in dirs_list:
                if _can_move(c, d, w, h):
                    return d

        return best_dir

    # -----------------------------------------------------------------------
    # DVD (movimiento aleatorio de emergencia)
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Exploración
    # -----------------------------------------------------------------------
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
                            and c.is_in_vision(nb)
                            and (c.is_tile_passable(nb) or c.is_tile_empty(nb))):
                        self._frontiers.add(nb)

        # Limitar memoria: descartar los más lejanos al bot
        if len(self._visited) > self._MAX_VISITED:
            current = c.get_position()
            sorted_v = sorted(self._visited,
                              key=lambda p: current.distance_squared(p))
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

        # Descartar target solo al llegar o si entró en visited
        # (NO al verlo — bug del original corregido)
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

        # BFS ligero solo si el target está en visión
        if c.is_in_vision(goal):
            if self._bfs_path_explore and not _can_move(c, self._bfs_path_explore[0], w, h):
                self._bfs_path_explore = []
            if not self._bfs_path_explore:
                self._bfs_path_explore = _bfs_in_vision(c, current, goal, w, h, max_nodes=80)
            if self._bfs_path_explore:
                nxt = self._bfs_path_explore[0]
                if _can_move(c, nxt, w, h):
                    self._bfs_path_explore.pop(0)
                    return nxt
                else:
                    self._bfs_path_explore = []
        else:
            self._bfs_path_explore = []

        # BugNav fallback para explore — mantiene su propio estado de goal
        if goal != self.prevGoal:
            self.reset()
            self.start = current
            self.prevGoal = goal
            self._hand_switches = 0

        return self._bugnav_step(c, goal, four_dirs)