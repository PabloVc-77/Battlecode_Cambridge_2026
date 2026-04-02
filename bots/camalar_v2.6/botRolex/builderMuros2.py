from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_opus as bugnav


def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return 0 <= pos.x < w and 0 <= pos.y < h


# Tipos de edificios enemigos que nos interesa destruir y tapiar
_ENEMY_TARGETS = (
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
)

_ALL_DIRS = (
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
)


class Muros:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()

        self.spawn: Position | None = None
        self.my_core: Position | None = None

        self.enemy_core_pos: Position | None = None
        self.enemy_core_candidates: list[Position] = []
        self.simetry: int = 0

        self.objetivo: Position | None = None

        # True cuando ya destruimos el edificio en objetivo y hay que colocar barrier.
        # Mientras sea True, _scan_enemies NO toca self.objetivo.
        self.pendiente_barrier: bool = False

        builds = ct.get_nearby_buildings()
        for b in builds:
            if ct.get_entity_type(b) == EntityType.CORE and ct.get_team(b) == ct.get_team():
                self.spawn = ct.get_position(b)
                self.my_core = self.spawn
                break

        if self.my_core is not None:
            self._init_enemy_candidates(ct.get_map_width(), ct.get_map_height())

    def _init_enemy_candidates(self, w: int, h: int):
        x, y = self.my_core.x, self.my_core.y
        self.enemy_core_candidates = [
            Position(w - 1 - x, y),
            Position(x, h - 1 - y),
            Position(w - 1 - x, h - 1 - y),
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Entrada principal
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        current = c.get_position()

        if c.can_heal(current):
            c.heal(current)

        # Inicialización tardía
        if self.my_core is None:
            for b in c.get_nearby_buildings():
                if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) == c.get_team():
                    self.my_core = c.get_position(b)
                    self.spawn = self.my_core
                    self._init_enemy_candidates(c.get_map_width(), c.get_map_height())
                    break

        # Escanear — respeta pendiente_barrier
        self._scan_enemies(c)

        if self.objetivo is not None:
            c.draw_indicator_dot(current, 255, 80, 0)
            c.draw_indicator_line(current, self.objetivo, 255, 80, 0)
            self._work_objetivo(c)
            return

        if self.enemy_core_pos is None:
            c.draw_indicator_dot(current, 255, 255, 0)
            self._find_enemy_core(c)
        else:
            c.draw_indicator_dot(current, 100, 100, 255)
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # Escaneo
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_enemies(self, c: Controller):
        current = c.get_position()

        # ── Validar objetivo actual ────────────────────────────────────────────
        if self.objetivo is not None:
            if c.is_in_vision(self.objetivo):
                bid = c.get_tile_building_id(self.objetivo)
                if self.pendiente_barrier:
                    # Estamos esperando para poner barrier: solo limpiar si ya
                    # hay nuestro edificio final o si el enemigo reconstruyó.
                    # si ya hay algo nuestro se olvida
                    if bid is not None and c.get_team(bid) == c.get_team():
                        # Barrier colocada: completado
                        self.objetivo = None
                        self.pendiente_barrier = False
                    # En cualquier otro caso (casilla vacía o enemigo de vuelta)
                    # dejamos objetivo intacto para que _work_objetivo gestione.
                    return  # no buscar nuevo objetivo
                else:
                    # Sin pendiente: si ya no hay enemigo, limpiar
                    if bid is None or c.get_team(bid) == c.get_team():
                        self.objetivo = None
            # Si no está en visión, mantener y acercarse

        # ── Buscar nuevo objetivo (solo si no tenemos) ─────────────────────────
        if self.objetivo is not None:
            # Tenemos objetivo sin pendiente: ver si hay uno MÁS CERCANO
            # (permitimos cambiar a uno más cercano, como pide el enunciado)
            best_pos: Position | None = None
            best_dist = float("inf")
            best_bid: int | None = None
            for bid in c.get_nearby_buildings():
                if c.get_team(bid) == c.get_team():
                    continue
                if c.get_entity_type(bid) not in _ENEMY_TARGETS:
                    continue
                pos = c.get_position(bid)
                dist = current.distance_squared(pos)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = pos
                    best_bid = bid
            # Cambiar solo si hay uno estrictamente más cercano que el actual
            if best_pos is not None and best_dist < current.distance_squared(self.objetivo):
                self.objetivo = best_pos
            return

        # Sin objetivo en absoluto: buscar el más cercano
        best_pos = None
        best_dist = float("inf")
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == c.get_team():
                continue
            if c.get_entity_type(bid) not in _ENEMY_TARGETS:
                continue
            pos = c.get_position(bid)
            dist = current.distance_squared(pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos
        self.objetivo = best_pos

    # ──────────────────────────────────────────────────────────────────────────
    # Trabajar sobre el objetivo
    # ──────────────────────────────────────────────────────────────────────────

    def _work_objetivo(self, c: Controller):
        current = c.get_position()
        target = self.objetivo

        # ── Acercarse si no está en visión ────────────────────────────────────
        if not c.is_in_vision(target):
            self._navigate_to(c, target)
            return

        bid = c.get_tile_building_id(target)

        # ── Casilla ya tiene nuestra barrier: completado ───────────────────────
        if bid is not None and c.get_team(bid) == c.get_team() \
                and c.get_entity_type(bid) == EntityType.BARRIER:
            self.objetivo = None
            self.pendiente_barrier = False
            return

        # ── Casilla libre (pendiente_barrier activo o recién vaciada) ─────────
        if bid is None or (bid is not None and c.get_team(bid) == c.get_team()
                           and c.get_entity_type(bid) != EntityType.BARRIER):
            # Si hay un edificio aliado que no es barrier (road, etc.), destruirlo
            if bid is not None and c.get_team(bid) == c.get_team():
                if c.can_destroy(target):
                    c.destroy(target)
                return  # siguiente tick: casilla libre

            # Casilla vacía: activar pendiente si no estaba
            self.pendiente_barrier = True

            # Salir de encima si estamos sobre el target
            if current == target:
                for d in _ALL_DIRS:
                    adj = target.add(d)
                    if _is_in_bounds(c, adj) and c.can_move(d):
                        c.move(d)
                        return
                return  # bloqueado: esperar

            # Acercarse si estamos lejos
            dist_sq = current.distance_squared(target)
            if dist_sq > 2:
                self._navigate_to(c, target)
                return

            # En rango (dist² <= 2) y no encima: construir barrier
            if c.can_build_barrier(target):
                c.build_barrier(target)
                self.objetivo = None
                self.pendiente_barrier = False
            # Si no puede aún (cooldown), espera — pendiente_barrier protege el objetivo
            return

        # ── Hay edificio enemigo ───────────────────────────────────────────────
        if current == target:
            if c.can_fire(target):
                c.fire(target)
            # Si lo destruimos en este tick, marcar pendiente
            if c.get_tile_building_id(target) is None:
                self.pendiente_barrier = True
            return

        # Movernos encima si es pisable; si no, acercarnos
        moved = False
        if c.is_tile_passable(target):
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
                moved = True
        else:
            if current.distance_squared(target) > 2:
                self._navigate_to(c, target)

        # Si llegamos encima, atacar en el mismo turno
        if moved and c.get_position() == target:
            if c.can_fire(target):
                c.fire(target)
            if c.get_tile_building_id(target) is None:
                self.pendiente_barrier = True

    # ──────────────────────────────────────────────────────────────────────────
    # Búsqueda del core enemigo por simetría
    # ──────────────────────────────────────────────────────────────────────────

    def _find_enemy_core(self, c: Controller):
        if not self.enemy_core_candidates:
            return
        target = self.enemy_core_candidates[self.simetry % len(self.enemy_core_candidates)]
        current = c.get_position()
        c.draw_indicator_line(current, target, 255, 140, 0)
        self._navigate_to(c, target)

        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if bid is not None and c.get_entity_type(bid) == EntityType.CORE \
                    and c.get_team(bid) != c.get_team():
                self.enemy_core_pos = target
            else:
                self.simetry += 1

        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
                self.enemy_core_pos = c.get_position(b)
                break

    # ──────────────────────────────────────────────────────────────────────────
    # Navegar hacia destino construyendo road
    # ──────────────────────────────────────────────────────────────────────────

    def _navigate_to(self, c: Controller, dest: Position):
        current = c.get_position()
        d = self.navegador.moveTo(c, dest, four_dirs=False)
        next_pos = current.add(d)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(d):
            c.move(d)