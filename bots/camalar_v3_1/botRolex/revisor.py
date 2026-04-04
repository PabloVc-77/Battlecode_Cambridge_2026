# inspector.py
from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav


def _is_in_bounds_inspector(map_w: int, map_h: int, pos: Position) -> bool:
    return 0 <= pos.x < map_w and 0 <= pos.y < map_h


class Inspector:
    """
    Bot inspector: hace un DFS de la red de puentes/conveyors desde el nexo
    hacia afuera, verificando que cada eslabón esté intacto y sea aliado.

    Modos:
      0 (INIT)     — Volver al spawn e inicializar el próximo ciclo de inspección
      1 (TRAVERSE) — DFS: moverse al siguiente nodo e inspeccionar
      2 (RETURN)   — DFS terminado, volver a casa y programar el siguiente ciclo
    """

    MODE_INIT     = 0
    MODE_TRAVERSE = 1
    MODE_RETURN   = 2

    # Cuántas rondas esperar entre ciclos completos de inspección
    INSPECTION_COOLDOWN = 40

    def __init__(self, c: Controller):
        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()
        self.navigator = bugnav.BugNav()
        self.spawn: Position | None = None
        self.end_bridges: list[Position] = []

        # Localizar el CORE
        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE:
                self.spawn = c.get_position(b)
                break

        # Calcular end_bridges (misma lógica que el Harvester)
        s = self.spawn
        candidates = [
            s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST),
            s.add(Direction.NORTH).add(Direction.NORTH),
            s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST),
            s.add(Direction.EAST).add(Direction.EAST).add(Direction.NORTH),
            s.add(Direction.EAST).add(Direction.EAST),
            s.add(Direction.EAST).add(Direction.EAST).add(Direction.SOUTH),
            s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST),
            s.add(Direction.SOUTH).add(Direction.SOUTH),
            s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST),
            s.add(Direction.WEST).add(Direction.WEST).add(Direction.NORTH),
            s.add(Direction.WEST).add(Direction.WEST),
            s.add(Direction.WEST).add(Direction.WEST).add(Direction.SOUTH),
        ]
        for v in candidates:
            if (self._in_bounds(v)
                    and c.is_in_vision(v)
                    and c.get_tile_env(v) != Environment.WALL):
                self.end_bridges.append(v)

        # ── Estado del DFS ────────────────────────────────────────────────────
        self.mode = self.MODE_INIT
        self.dfs_stack:     list[Position] = []   # posiciones de puente por visitar
        self.scheduled:     set[Position]  = set() # mirror del stack para O(1) lookup
        self.visited:       set[Position]  = set() # ya inspeccionados este ciclo
        self.broken:        list[Position] = []    # eslabones rotos encontrados

        self.current_target: Position | None = None
        self.next_inspection_round: int = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Utilidades
    # ─────────────────────────────────────────────────────────────────────────

    def _in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        if direction == Direction.CENTRE:
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    def _bridge_target_of(self, c: Controller, build_id) -> Position | None:
        """Devuelve la casilla 'hacia spawn' del puente o conveyor dado."""
        etype = c.get_entity_type(build_id)
        if etype == EntityType.BRIDGE:
            return c.get_bridge_target(build_id)
        if etype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            pos = c.get_position(build_id)
            return pos.add(c.get_direction(build_id))
        return None

    def _is_chain_element(self, etype: EntityType) -> bool:
        return etype in (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        )

    def _push_if_new(self, pos: Position):
        """Añade pos al stack sólo si no se ha visitado ni programado ya."""
        if pos not in self.visited and pos not in self.scheduled:
            self.dfs_stack.append(pos)
            self.scheduled.add(pos)

    # ─────────────────────────────────────────────────────────────────────────
    # Lógica del DFS
    # ─────────────────────────────────────────────────────────────────────────

    def _seed_dfs(self, c: Controller):
        """
        Primer nivel del DFS: busca puentes/conveyors cuyo target apunte
        directamente a alguna de las end_bridges. Se llama estando en el spawn.
        """
        self.dfs_stack  = []
        self.scheduled  = set()
        self.visited    = set()
        self.broken     = []

        end_set = set(self.end_bridges)

        for b in c.get_nearby_buildings():
            if not self._is_chain_element(c.get_entity_type(b)):
                continue
            if c.get_team(b) != c.get_team():
                continue
            b_pos  = c.get_position(b)
            target = self._bridge_target_of(c, b)
            if target in end_set:
                self._push_if_new(b_pos)

    def _inspect_and_expand(self, c: Controller, pos: Position):
        """
        Inspecciona el eslabón en `pos`:
          1. Verifica que exista un puente/conveyor aliado.
          2. Verifica que su target sea válido (end_bridge o puente aliado).
          3. Expande el DFS: busca edificios cercanos cuyo target == pos.
        """
        if not c.is_in_vision(pos):
            # Sin visión: no podemos determinar el estado. Ignorar este nodo.
            return

        build_id = c.get_tile_building_id(pos)

        # ── Verificación del eslabón en pos ───────────────────────────────────
        if (build_id is None
                or not self._is_chain_element(c.get_entity_type(build_id))
                or c.get_team(build_id) != c.get_team()):
            # Hueco o edificio ajeno: eslabón roto
            if pos not in self.broken:
                self.broken.append(pos)
                c.draw_indicator_dot(pos, 255, 0, 0)  # rojo = roto
            return

        # Eslabón OK → verificar su target
        target = self._bridge_target_of(c, build_id)
        if target is not None and target not in self.end_bridges:
            if c.is_in_vision(target):
                tid = c.get_tile_building_id(target)
                if (tid is None
                        or not self._is_chain_element(c.get_entity_type(tid))
                        or c.get_team(tid) != c.get_team()):
                    if target not in self.broken:
                        self.broken.append(target)
                        c.draw_indicator_dot(target, 255, 80, 0)  # naranja = target roto

        c.draw_indicator_dot(pos, 0, 220, 255)  # cian = inspeccionado OK

        # ── Expansión DFS: quién apunta HACIA pos ─────────────────────────────
        for b in c.get_nearby_buildings():
            if not self._is_chain_element(c.get_entity_type(b)):
                continue
            if c.get_team(b) != c.get_team():
                continue
            b_pos   = c.get_position(b)
            b_target = self._bridge_target_of(c, b)
            if b_target == pos:
                self._push_if_new(b_pos)

    # ─────────────────────────────────────────────────────────────────────────
    # Bucle principal
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        current = c.get_position()

        # ── Modo 0: INIT — esperar y volver al spawn ──────────────────────────
        if self.mode == self.MODE_INIT:
            c.draw_indicator_dot(current, 128, 128, 128)  # gris = esperando

            if c.get_current_round() < self.next_inspection_round:
                return  # Cooldown activo

            # Acercarse al spawn para tener visión de end_bridges
            if current.distance_squared(self.spawn) > 4:
                d = self.navigator.moveTo(c, self.spawn, four_dirs=False)
                next_pos = current.add(d)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, d)
                return

            # En spawn: sembrar el DFS con los puentes de nivel 1
            self._seed_dfs(c)

            if self.dfs_stack:
                self.mode = self.MODE_TRAVERSE
            else:
                # Sin puentes todavía: reintentar en 10 rondas
                self.next_inspection_round = c.get_current_round() + 10

        # ── Modo 1: TRAVERSE — DFS de la red de puentes ───────────────────────
        elif self.mode == self.MODE_TRAVERSE:
            c.draw_indicator_dot(current, 0, 180, 255)  # azul = inspeccionando

            # Elegir siguiente nodo del stack (saltando ya visitados)
            while self.current_target is None:
                if not self.dfs_stack:
                    self.mode = self.MODE_RETURN
                    return
                candidate = self.dfs_stack.pop()
                self.scheduled.discard(candidate)
                if candidate not in self.visited:
                    self.current_target = candidate

            c.draw_indicator_dot(self.current_target, 255, 165, 0)           # naranja = objetivo
            c.draw_indicator_line(current, self.current_target, 0, 180, 255)  # línea azul

            # Moverse hasta tener visión del objetivo
            if not c.is_in_vision(self.current_target):
                d = self.navigator.moveTo(c, self.current_target, four_dirs=False)
                next_pos = current.add(d)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, d)
                return

            # Tenemos visión: inspeccionar y expandir el DFS
            self._inspect_and_expand(c, self.current_target)
            self.visited.add(self.current_target)
            self.current_target = None

        # ── Modo 2: RETURN — volver al spawn y programar siguiente ciclo ──────
        elif self.mode == self.MODE_RETURN:
            c.draw_indicator_dot(current, 200, 50, 200)  # morado = volviendo

            # Remarcar todos los eslabones rotos cada turno
            for bp in self.broken:
                c.draw_indicator_dot(bp, 255, 0, 0)

            if current.distance_squared(self.spawn) > 4:
                d = self.navigator.moveTo(c, self.spawn, four_dirs=False)
                self._try_move(c, d)
                return

            # En casa: programar próxima inspección
            self.next_inspection_round = c.get_current_round() + self.INSPECTION_COOLDOWN
            self.current_target = None
            self.mode = self.MODE_INIT