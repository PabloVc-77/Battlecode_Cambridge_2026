from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav


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

        # True cuando el objetivo es un destino libre de puente enemigo:
        # no hay que destruir nada, ir directo a construir la barrier.
        self.objetivo_es_destino_libre: bool = False

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
                if self.pendiente_barrier or self.objetivo_es_destino_libre:
                    # Estamos colocando barrier: solo limpiar si ya está puesta
                    # o si el enemigo ha bloqueado la casilla de destino libre.
                    if bid is not None and c.get_team(bid) == c.get_team() \
                            and c.get_entity_type(bid) == EntityType.BARRIER:
                        self.objetivo = None
                        self.pendiente_barrier = False
                        self.objetivo_es_destino_libre = False
                    elif self.objetivo_es_destino_libre and bid is not None \
                            and c.get_team(bid) != c.get_team():
                        # El enemigo puso algo en la casilla destino:
                        # ya no es un destino libre, olvidar y re-escanear
                        self.objetivo = None
                        self.objetivo_es_destino_libre = False
                    return  # no buscar nuevo objetivo mientras hay trabajo pendiente
                else:
                    if bid is None or c.get_team(bid) == c.get_team():
                        self.objetivo = None
                        self.objetivo_es_destino_libre = False
            # Si no está en visión, mantener y acercarse

        # ── Recopilar todos los edificios enemigos en visión una sola vez ──────
        enemy_bridges: list[int] = []
        enemy_targets: list[tuple[int, Position, float]] = []  # (bid, pos, dist²)

        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == c.get_team():
                continue
            etype = c.get_entity_type(bid)
            if etype == EntityType.BRIDGE:
                enemy_bridges.append(bid)
            if etype in _ENEMY_TARGETS:
                pos = c.get_position(bid)
                dist = current.distance_squared(pos)
                enemy_targets.append((bid, pos, dist))

        # ── Prioridad 1: destinos libres de puentes enemigos ──────────────────
        # Un destino libre es más urgente que destruir: podemos tapar directamente.
        best_free_pos: Position | None = None
        best_free_dist = float("inf")

        for bid in enemy_bridges:
            dest = c.get_bridge_target(bid)
            if dest is None:
                continue
            if not _is_in_bounds(c, dest):
                continue
            if not c.is_in_vision(dest):
                continue
            tile_bid = c.get_tile_building_id(dest)
            if tile_bid is not None:
                continue  # casilla ocupada: no es destino libre
            dist = current.distance_squared(dest)
            if dist < best_free_dist:
                best_free_dist = dist
                best_free_pos = dest

        if best_free_pos is not None:
            # Si ya tenemos un objetivo de destino libre más cercano, mantenerlo;
            # si hay uno más cercano, cambiar.
            if self.objetivo_es_destino_libre and self.objetivo is not None:
                if best_free_dist < current.distance_squared(self.objetivo):
                    self.objetivo = best_free_pos
                    self.pendiente_barrier = True   # directo a colocar barrier
            else:
                self.objetivo = best_free_pos
                self.objetivo_es_destino_libre = True
                self.pendiente_barrier = True       # no hay que destruir nada
            return

        # Si teníamos objetivo de destino libre pero ya no hay ninguno libre,
        # limpiar para buscar target normal
        if self.objetivo_es_destino_libre:
            self.objetivo = None
            self.objetivo_es_destino_libre = False
            self.pendiente_barrier = False

        # ── Prioridad 2: targets normales (destruir + tapar) ──────────────────
        if self.objetivo is not None:
            # Ya tenemos objetivo: cambiar solo si hay uno más cercano
            best_pos = min(enemy_targets, key=lambda t: t[2], default=None)
            if best_pos is not None:
                bp_pos, bp_dist = best_pos[1], best_pos[2]
                if bp_dist < current.distance_squared(self.objetivo):
                    self.objetivo = bp_pos
                    self.pendiente_barrier = False
            return

        # Sin objetivo: tomar el más cercano
        if enemy_targets:
            best = min(enemy_targets, key=lambda t: t[2])
            self.objetivo = best[1]
            self.objetivo_es_destino_libre = False
            self.pendiente_barrier = False

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
        if bid is not None and c.get_team(bid) == c.get_team():
            self.objetivo = None
            self.pendiente_barrier = False
            self.objetivo_es_destino_libre = False
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
                self.objetivo_es_destino_libre = False
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