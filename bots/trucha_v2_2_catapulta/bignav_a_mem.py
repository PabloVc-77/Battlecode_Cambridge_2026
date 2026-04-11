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

MAPA PERSISTENTE:
─────────────────
BugNav mantiene dos sets que sobreviven entre ticks y entre instancias
de AStarState:
  - _map_passable: tiles confirmados como transitables.
  - _map_blocked:  tiles confirmados como bloqueados.
Cada tick se actualizan con todos los tiles visibles mediante
_update_map(c). El A* consulta primero el mapa persistente y solo
llama a is_in_vision/is_tile_passable para tiles aún desconocidos,
lo que le permite planificar rutas a través de zonas ya exploradas
aunque estén fuera de visión en ese momento.

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

from cambc import Controller, Direction, Position, EntityType, Environment
import math
import random

from map_symmetry import MapSymmetry

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CPU_BUDGET_US = 1200      # µs máximos por tick antes de ceder el control
BFS_MAX_NODES = 80        # BFS rápido cuando goal está en visión

_ALL_DIRS = [
    Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
    Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST,
]
_CARD_DIRS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

# ---------------------------------------------------------------------------
# Instancia global de simetría — importable desde otros módulos:
#   from bugnav import MAP_SYM
# ---------------------------------------------------------------------------

MAP_SYM = MapSymmetry()

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
    id = c.get_tile_building_id(nxt)
    #if id is not None and c.get_entity_type(id) == EntityType.BARRIER and c.get_team(id) == c.get_team():
    #    return True
    if c.get_entity_type(id) == EntityType.MARKER:
        return True
    return c.can_move(d) or c.is_tile_empty(nxt) or c.is_tile_passable(nxt)


def _passable(c: Controller, pos: Position) -> bool:
    if c.is_tile_empty(pos):
        return True
    
    from cambc import Environment, EntityType
    if c.get_tile_env(pos) == Environment.WALL:
        return False
        
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return True
        
    b_type = c.get_entity_type(bid)
    if b_type in (EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE):
        return True
    if b_type == EntityType.CORE and c.get_team(bid) == c.get_team():
        return True
        
    return False


def _passable_known(c: Controller, pos: Position,
                    map_passable: set, map_blocked: set,
                    map_walls: set | None = None) -> bool:
    """
    Consulta el mapa persistente primero; solo llama a la API del controlador
    para tiles aún desconocidos (en visión actual).
    Devuelve True si el tile es transitable según la mejor información disponible.

    map_walls (opcional): set de paredes permanentes (Environment.WALL).
    Si se pasa, los tiles en map_walls se consideran bloqueados definitivamente
    incluso si no están en map_blocked en este momento (p.ej. porque hay un
    edificio encima y ya no están en visión directa).
    """
    # Paredes permanentes: bloqueadas para siempre, sin excepción
    if map_walls is not None and pos in map_walls:
        return False
    if pos in map_passable:
        return True
    if pos in map_blocked:
        return False
    # Tile desconocido: solo consultable si está en visión ahora mismo
    if c.is_in_vision(pos):
        return _passable(c, pos)
    # Fuera de visión y sin datos: asumir no transitable (conservador)
    return False

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

def _astar_tick(state: AStarState, c: Controller, w: int, h: int,
                map_passable: set, map_blocked: set,
                map_walls: set | None = None) -> None:
    """
    Avanza el A* mientras quede presupuesto de CPU en el tick actual.
    Comprueba c.get_cpu_time_elapsed() en cada iteración; si supera
    CPU_BUDGET_US, devuelve el control sin marcar done, para reanudar
    en el siguiente tick. BugNav cubre el movimiento mientras tanto.

    Usa el mapa persistente (map_passable / map_blocked) para explorar
    tiles ya conocidos aunque estén fuera de visión en este tick.

    map_walls: set de paredes permanentes (Environment.WALL). Los tiles
    en este set se tratan como bloqueados de forma definitiva, lo que
    permite al A* planificar rutas correctas por zonas ya exploradas
    aunque los tiles de pared hayan salido del campo de visión.
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
            # El goal se acepta siempre (no necesitamos "atravesarlo", solo llegar).
            # El resto de tiles requieren ser transitables según el mapa conocido.
            if nb != goal and not _passable_known(c, nb, map_passable, map_blocked, map_walls):
                continue
            step = 1.414 if _is_diagonal(d) else 1.0
            ng = g + step
            if ng >= g_best.get(nb, float("inf")):
                continue
            g_best[nb] = ng
            parent[nb] = (pos, d)
            h_val = math.sqrt(nb.distance_squared(goal))
            ol.append([ng + h_val, ng, nb])

    # open_list vacía: goal inalcanzable con el mapa conocido actual
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
        self._astar_failed_goal: Position | None = None  # goal para el que A* ya agotó el mapa
        
        # Salto de Muros cooperative mechanic
        self._jump_failed_goal: Position | None = None
        self._jump_state = "IDLE"
        self._jump_landing_target: Position | None = None
        self._jump_wait_ticks = 0
        # Posiciones desde las que ya lanzamos un salto para el goal actual.
        # Evita el bucle saltar→aterrizar→volver→saltar desde el mismo sitio.
        self._jumped_from_positions: set = set()

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

        # Mapa persistente: tiles conocidos que sobreviven entre ticks
        # Se actualiza cada tick con _update_map(c) y lo consulta el A*
        # para planificar rutas por zonas ya exploradas aunque no estén en visión
        self._map_passable: set = set()   # tiles confirmados como transitables
        self._map_blocked:  set = set()   # tiles confirmados como bloqueados

        # Paredes permanentes: subconjunto de _map_blocked con Environment.WALL
        # Nunca se eliminan de este set porque las paredes son inmutables.
        # El A* puede confiar en que estos tiles jamás serán transitables,
        # lo que mejora la planificación en zonas ya exploradas.
        self._map_walls: set = set()

    # -------------------------------------------------------------------------
    def _init_dims(self, c: Controller):
        if self._w == 0:
            self._w = c.get_map_width()
            self._h = c.get_map_height()

    def _update_map(self, c: Controller):
        """
        Registra en el mapa persistente todos los tiles visibles este tick.

        - _map_passable / _map_blocked: para el pathfinding dinámico del A*.
        - _map_walls: subconjunto permanente de paredes (Environment.WALL).
        - MAP_SYM: recibe el entorno de cada tile para el detector de simetría
          (filtra EMPTY internamente; solo procesa WALL y ORE_*).

        Las paredes son el único tipo de tile bloqueado que nunca cambia,
        así que se guardan en _map_walls y se usan para reforzar _map_blocked
        incluso si una construcción posterior "tapa" la pared en visión.
        """
        w, h = self._w, self._h
        for pos in c.get_nearby_tiles():
            env = c.get_tile_env(pos)

            # --- Detector de simetría (terreno estático: WALL y ORE_*) ---
            MAP_SYM.update_terrain(pos, env, w, h)

            # --- Mapa dinámico para pathfinding ---
            if _passable(c, pos):
                self._map_passable.add(pos)
                self._map_blocked.discard(pos)
                # Nota: las paredes nunca son pasables, así que este branch
                # no interfiere con _map_walls
            else:
                self._map_blocked.add(pos)
                self._map_passable.discard(pos)

                # Si el tile es una pared permanente, registrarla por separado.
                # Esto permite al A* tratarla como bloqueada definitiva aunque
                # en un tick futuro haya un edificio encima y el tile no esté
                # en visión (evita que _map_blocked la pierda por discard).
                if env == Environment.WALL:
                    self._map_walls.add(pos)

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
        self._astar_failed_goal = None
        self._jump_failed_goal = None
        self._jump_state = "IDLE"
        self._jump_landing_target = None
        self._jump_wait_ticks = 0
        self._jumped_from_positions = set()

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

        # Actualizar mapa persistente con los tiles visibles este tick
        self._update_map(c)

        if goal != self.prevGoal:
            self._full_reset()
            self.start = current
            self.prevGoal = goal

        # ── Detectar aterrizaje post-salto ────────────────────────────────────
        # Si el jump_state era MARKER_PLACED y la posición actual es distinta
        # al landing esperado (o simplemente cambió respecto al tick anterior),
        # significa que fuimos lanzados. Reiniciar A* desde la nueva posición
        # para que busque camino desde aquí sin la restricción del failed_goal.
        if self._jump_state == "MARKER_PLACED" and current != self.start:
            # Registrar la posición de origen del salto para no repetirlo
            if self.start is not None:
                self._jumped_from_positions.add(self.start)
            # Reiniciar pathfinding desde la nueva posición
            self._astar_failed_goal = None
            self._astar = None
            self._path = []
            self._bfs_path = []
            self._jump_state = "IDLE"
            self._jump_landing_target = None
            self._jump_wait_ticks = 0
            self.start = current
            self.reset()

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
        elif self._bfs_path and _can_move(c, self._bfs_path[0], w, h):
            return self._consume_path(c, self._bfs_path, four_dirs, w, h)
        else:
            self._bfs_path = []

        # ── 2. A* incremental en background ──────────────────────────────────
        astar_blocked = (self._astar_failed_goal == goal)

        # Si ya estamos en medio del proceso de salto, continuarlo
        if self._jump_state != "IDLE":
            jump_dir = self._try_jumping_mechanic(c, goal, w, h)
            if jump_dir is not None:
                return jump_dir
        # Solo intentar el salto si A* terminó y FALLÓ definitivamente,
        # el A* no está en curso, no tenemos path, y llevamos bordando un rato.
        elif (astar_blocked
              and self._astar is None
              and not self._path
              and self._jump_failed_goal != goal
              and self.wall_steps > 15):
            jump_dir = self._try_jumping_mechanic(c, goal, w, h)
            if jump_dir is not None:
                return jump_dir

        if not astar_blocked and self._astar is None and not self._path:
            self._astar = AStarState(current, goal)

        if self._astar is not None and self._astar.is_active():
            _astar_tick(self._astar, c, w, h, self._map_passable, self._map_blocked, self._map_walls)
            if self._astar.done:
                if self._astar.path:
                    self._path = self._trim_path(current, self._astar.path)
                    self._astar_failed_goal = None
                else:
                    # A* agotó el mapa sin encontrar camino: marcar como fallido
                    self._astar_failed_goal = goal
                self._astar = None

        if self._path:
            if not _can_move(c, self._path[0], w, h):
                # Path bloqueado por cambio de mapa — reiniciar A* solo si el
                # goal en sí es alcanzable (no estaba marcado como fallido)
                self._astar_failed_goal = None
                self._astar = AStarState(current, goal)
                self._path = []
            else:
                return self._consume_path(c, self._path, four_dirs, w, h)

        # ── 3. BugNav mientras A* calcula (garantía de movimiento) ───────────
        # BugNav siempre devuelve una dirección válida; si está en modo GOAL y
        # no puede avanzar directo, entra en wall-following. El A* continúa en
        # background y reemplaza a BugNav en cuanto termina.
        return self._bugnav_step(c, goal, four_dirs)

    # =========================================================================
    # Mecanica de Salto de Muros
    # =========================================================================

    # Posiciones desde las que ya fuimos lanzados para este goal.
    # Al aterrizar en una nueva posición, el A* se reinicia desde ahí,
    # pero si el mapa sigue siendo el mismo y vuelve a fallar, NO saltamos
    # desde una posición que ya usamos (evita el bucle saltar→volver→saltar).
    # Se limpia en _full_reset (cuando cambia el goal).

    def _find_unreachable_better_tile(self, c: Controller, current: Position, goal: Position, w: int, h: int) -> Position | None:
        """
        Busca el mejor tile de aterrizaje que:
          1. No sea alcanzable caminando desde current (según mapa visible).
          2. Sea lanzable desde alguna posición adyacente al bot donde
             se pueda construir un launcher (casilla vacía o road propia).
          3. Mejore significativamente la distancia al goal respecto a current.
        """
        LAUNCHER_RANGE_SQ = 26
        BOT_VISION_SQ = 20

        # 1. BFS para encontrar todo lo conectable caminando desde current
        walkable: set = {current}
        queue = [current]
        head = 0
        while head < len(queue):
            pos = queue[head]; head += 1
            for d in _ALL_DIRS:
                nb = pos.add(d)
                if nb not in walkable and _in_bounds(nb, w, h):
                    if current.distance_squared(nb) <= BOT_VISION_SQ:
                        if c.is_in_vision(nb) and _passable(c, nb):
                            walkable.add(nb)
                            queue.append(nb)

        # 2. Posibles posiciones del launcher: adyacentes al bot que estén
        #    vacías, tengan una road propia (destruible), o ya tengan un launcher aliado.
        launcher_candidates: list[Position] = []
        for d in _ALL_DIRS:
            adj = current.add(d)
            if not _in_bounds(adj, w, h) or not c.is_in_vision(adj):
                continue
            bid = c.get_tile_building_id(adj)
            if bid is None:
                launcher_candidates.append(adj)
            else:
                et = c.get_entity_type(bid)
                team = c.get_team(bid)
                if et == EntityType.LAUNCHER and team == c.get_team():
                    launcher_candidates.append(adj)
                elif et == EntityType.ROAD and team == c.get_team():
                    # Road propia: destruible para poner el launcher
                    launcher_candidates.append(adj)

        if not launcher_candidates:
            return None

        # 3. Mejor tile de aterrizaje: no walkable, pasable, alcanzable desde
        #    algún launcher_candidate, y que mejore la distancia al goal.
        current_dist = current.distance_squared(goal)
        best_landing: Position | None = None
        best_dist = current_dist - 4  # mejora mínima exigida

        for tile in c.get_nearby_tiles():
            if tile in walkable:
                continue
            if not c.is_tile_passable(tile):
                continue
            tile_dist = tile.distance_squared(goal)
            if tile_dist >= best_dist:
                continue
            for lpos in launcher_candidates:
                dsq = lpos.distance_squared(tile)
                if 0 < dsq <= LAUNCHER_RANGE_SQ:
                    best_dist = tile_dist
                    best_landing = tile
                    break

        return best_landing

    def _try_jumping_mechanic(self, c: Controller, goal: Position, w: int, h: int) -> Direction | None:
        """
        Máquina de estados para el salto cooperativo con el Launcher:
          IDLE          → evaluar si tiene sentido saltar y calcular landing
          BUILDING      → construir launcher / esperar recursos
          MARKER_PLACED → marker colocado, esperar a ser lanzado
        
        Anti-bucle: tras aterrizar en una nueva posición, el A* se relanza
        desde ahí (_astar_failed_goal se limpia en _full_reset cuando el goal
        cambia, pero cuando el goal ES el mismo se limpia explícitamente aquí
        al registrar el salto en _jumped_from_positions).
        """
        current = c.get_position()

        # ── Estado IDLE: evaluar si vale la pena saltar ───────────────────────
        if self._jump_state == "IDLE":
            # No saltar desde una posición que ya usamos para este goal
            if current in self._jumped_from_positions:
                return None
            landing = self._find_unreachable_better_tile(c, current, goal, w, h)
            if landing is None:
                return None
            self._jump_landing_target = landing

        LAUNCHER_RANGE_SQ = 26
        landing = self._jump_landing_target

        # ── Buscar launcher adyacente aliado existente ────────────────────────
        launcher_pos: Position | None = None
        for d in _ALL_DIRS:
            adj = current.add(d)
            if not _in_bounds(adj, w, h): continue
            bid = c.get_tile_building_id(adj)
            if bid is not None and c.get_entity_type(bid) == EntityType.LAUNCHER and c.get_team(bid) == c.get_team():
                launcher_pos = adj
                break

        # ── Si no hay launcher, construirlo ───────────────────────────────────
        if launcher_pos is None:
            for d in _ALL_DIRS:
                adj = current.add(d)
                if not _in_bounds(adj, w, h) or not c.is_in_vision(adj): continue
                # Verificar rango al landing
                if landing is not None and not (0 < adj.distance_squared(landing) <= LAUNCHER_RANGE_SQ):
                    continue
                bid = c.get_tile_building_id(adj)
                # Destruir road propia si la hay (no bloquea)
                if bid is not None:
                    et = c.get_entity_type(bid)
                    tm = c.get_team(bid)
                    if et == EntityType.ROAD and tm == c.get_team():
                        if c.can_destroy(adj):
                            c.destroy(adj)
                        # La road se destruye pero el build ocurre el próximo tick
                        self._jump_state = "BUILDING"
                        return Direction.CENTRE
                    else:
                        continue  # ocupado por algo que no podemos quitar
                if c.can_build_launcher(adj):
                    c.build_launcher(adj)
                    launcher_pos = adj
                    self._jump_state = "BUILDING"
                    return Direction.CENTRE
            # No pudimos construir este tick
            self._jump_state = "BUILDING"
            return Direction.CENTRE

        # ── Tenemos launcher: verificar que alcanza el landing ────────────────
        if landing is not None and not (0 < launcher_pos.distance_squared(landing) <= LAUNCHER_RANGE_SQ):
            # El launcher no tiene rango al landing actual — recalcular
            new_landing = self._find_unreachable_better_tile(c, current, goal, w, h)
            if new_landing is None or not (0 < launcher_pos.distance_squared(new_landing) <= LAUNCHER_RANGE_SQ):
                self._jump_state = "IDLE"
                self._jump_failed_goal = goal
                return None
            self._jump_landing_target = new_landing
            landing = new_landing

        # ── Buscar marker nuestro adyacente al launcher con el valor correcto ─
        marker_pos: Position | None = None
        expected_val = landing.x * 1000 + landing.y if landing is not None else -1
        for d in _ALL_DIRS:
            adj = launcher_pos.add(d)
            if not _in_bounds(adj, w, h) or not c.is_in_vision(adj): continue
            if adj == current: continue
            bid = c.get_tile_building_id(adj)
            if bid is None: continue
            if c.get_entity_type(bid) != EntityType.MARKER: continue
            if c.get_team(bid) != c.get_team(): continue
            if c.get_marker_value(bid) == expected_val:
                marker_pos = adj
                break

        # ── Marker ya colocado: esperar a ser lanzado ─────────────────────────
        if marker_pos is not None:
            self._jump_state = "MARKER_PLACED"
            self._jump_wait_ticks = 0
            return Direction.CENTRE

        # ── Marker no encontrado ──────────────────────────────────────────────
        if self._jump_state == "MARKER_PLACED":
            # El launcher destruyó el marker → o nos lanzó o no pudo.
            self._jump_wait_ticks += 1
            if self._jump_wait_ticks > 3:
                self._jumped_from_positions.add(current)
                self._jump_state = "IDLE"
                self._jump_wait_ticks = 0
                self._jump_landing_target = None
                self._astar_failed_goal = None
                return None
            return Direction.CENTRE

        # ── Colocar marker ────────────────────────────────────────────────────
        # El action radius del builder bot es dist²≤2, así que solo podemos
        # poner markers en casillas inmediatamente adyacentes (dist²≤2 desde current).
        # Buscamos casillas que estén adyacentes al launcher Y dentro de nuestro rango.
        t = landing if landing is not None else goal
        valor = t.x * 1000 + t.y

        ACTION_RADIUS_SQ = 2  # radio de acción del builder bot

        # Prioridad 1: casillas adyacentes al launcher que también estén en nuestro radio
        for d in _ALL_DIRS:
            adj = launcher_pos.add(d)
            if not _in_bounds(adj, w, h): continue
            if adj == current: continue
            if adj == launcher_pos: continue
            # Verificar que está dentro del action radius del bot
            if current.distance_squared(adj) > ACTION_RADIUS_SQ: continue
            if c.can_place_marker(adj):
                c.place_marker(adj, valor)
                self._jump_state = "MARKER_PLACED"
                self._jump_wait_ticks = 0
                return Direction.CENTRE

        # Prioridad 2: cualquier casilla en nuestro radio de acción (el launcher
        # también busca en sus adyacentes, así que lo encontrará igualmente)
        for d in _ALL_DIRS:
            adj = current.add(d)
            if not _in_bounds(adj, w, h): continue
            if adj == launcher_pos: continue
            if current.distance_squared(adj) > ACTION_RADIUS_SQ: continue
            if c.can_place_marker(adj):
                c.place_marker(adj, valor)
                self._jump_state = "MARKER_PLACED"
                self._jump_wait_ticks = 0
                return Direction.CENTRE

        # Prioridad 3: en la propia posición del bot (dist²=0, siempre en rango)
        if c.can_place_marker(current):
            c.place_marker(current, valor)
            self._jump_state = "MARKER_PLACED"
            self._jump_wait_ticks = 0
            return Direction.CENTRE

        # No pudo colocar marker este tick — esperar
        self._jump_wait_ticks += 1
        if self._jump_wait_ticks > 5:
            self._jump_state = "IDLE"
            self._jump_failed_goal = goal
            self._jump_wait_ticks = 0
            return None
        self._jump_state = "BUILDING"
        return Direction.CENTRE

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
        self._update_map(c)
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