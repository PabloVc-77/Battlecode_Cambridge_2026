from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_a_mem as bugnav
from bignav_a_mem import MAP_SYM

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return 0 <= pos.x < w and 0 <= pos.y < h


_TURRET_TYPES = (EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH)

_ALL_DIRS = (
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
)

_CARD_DIRS = (
    Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
)

# Turnos consecutivos atacando sin progreso antes de marcar como bloqueado
_STALL_THRESHOLD = 8
# Turnos que un objetivo permanece bloqueado antes de reintentarse
_BLOCK_COOLDOWN = 50


class Ataque:
    def __init__(self, ct: Controller):
        self.navegador = bugnav.BugNav()

        self.spawn: Position | None = None
        self.my_core: Position | None = None

        self.enemy_core_pos: Position | None = None
        self.enemy_core_candidates: list[Position] = []
        self.simetry: int = 0
        self.has_seen_enemy_core = False

        self.objetivo: Position | None = None

        # True cuando el objetivo es una casilla adyacente a un harvester enemigo
        self.objetivo_es_harvester_adj: bool = False

        # True cuando ya destruimos el edificio en objetivo y hay que colocar torreta.
        # Mientras sea True, _scan_enemies NO toca self.objetivo.
        self.pendiente_torreta: bool = False

        # True cuando el objetivo es un destino libre de puente/conveyor enemigo:
        # no hay que destruir nada, ir directo a construir la torreta.
        self.objetivo_es_destino_libre: bool = False

        # ── Detección de estancamiento ────────────────────────────────────────
        self._stall_objetivo: Position | None = None  # objetivo que estamos vigilando
        self._stall_turns: int = 0                    # turnos consecutivos sin progreso
        self._last_objetivo_hp: int | None = None     # HP del edificio en objetivo el tick anterior

        # {pos: round_blocked} — objetivos temporalmente descartados
        self._blocked_objectives: dict[Position, int] = {}

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
        ronda = c.get_current_round()
        if ronda < 200:
            return
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
        
        if self.enemy_core_pos is None and MAP_SYM.confirmed():
            self.enemy_core_pos = MAP_SYM.symmetric_pos(self.my_core, c.get_map_width(), c.get_map_height())

        # Limpiar objetivos bloqueados que ya han expirado
        self._refresh_blocked(c)

        # Detectar estancamiento sobre el objetivo actual
        self._check_stall(c)

        # Escanear — respeta pendiente_torreta
        self._scan_enemies(c)

        if self.objetivo is not None:
            c.draw_indicator_dot(current, 255, 80, 0)
            c.draw_indicator_line(current, self.objetivo, 255, 80, 0)
            self._work_objetivo(c)
            return

        if self.enemy_core_pos is None:
            c.draw_indicator_dot(current, 255, 255, 0)
            self._find_enemy_core(c)
        elif not self.has_seen_enemy_core:
            self.go_to_enemy_core(c)
        else:
            c.draw_indicator_dot(current, 100, 100, 255)
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # Gestión de objetivos bloqueados
    # ──────────────────────────────────────────────────────────────────────────

    def _refresh_blocked(self, c: Controller):
        """Elimina del diccionario los objetivos cuyo cooldown ya expiró."""
        current_round = c.get_current_round()
        expired = [pos for pos, blocked_round in self._blocked_objectives.items()
                   if current_round - blocked_round >= _BLOCK_COOLDOWN]
        for pos in expired:
            del self._blocked_objectives[pos]

    def _is_blocked(self, pos: Position) -> bool:
        return pos in self._blocked_objectives

    def _block_objetivo(self, c: Controller):
        """Marca el objetivo actual como bloqueado y lo descarta."""
        if self.objetivo is not None:
            self._blocked_objectives[self.objetivo] = c.get_current_round()
        self.objetivo = None
        self.pendiente_torreta = False
        self.objetivo_es_destino_libre = False
        self.objetivo_es_harvester_adj = False
        self._stall_turns = 0
        self._last_objetivo_hp = None
        self._stall_objetivo = None

    # ──────────────────────────────────────────────────────────────────────────
    # Detección de estancamiento
    # ──────────────────────────────────────────────────────────────────────────

    def _check_stall(self, c: Controller):
        """
        Comprueba si llevamos demasiados turnos sin progresar en el objetivo actual.
        Solo cuenta cuando estamos cerca (dist² <= 2) y hay un edificio enemigo.
        Si el HP no baja en _STALL_THRESHOLD turnos consecutivos, bloqueamos el objetivo.
        """
        if self.objetivo is None or self.pendiente_torreta:
            self._stall_turns = 0
            self._last_objetivo_hp = None
            self._stall_objetivo = None
            return

        target = self.objetivo

        if self._stall_objetivo != target:
            self._stall_objetivo = target
            self._stall_turns = 0
            self._last_objetivo_hp = None

        if not c.is_in_vision(target):
            return

        bid = c.get_tile_building_id(target)
        if bid is None or c.get_team(bid) == c.get_team():
            self._stall_turns = 0
            self._last_objetivo_hp = None
            return

        current = c.get_position()
        dist = current.distance_squared(target)

        if dist > 2:
            self._stall_turns = 0
            self._last_objetivo_hp = None
            return

        current_hp = c.get_hp(bid)

        if self._last_objetivo_hp is not None:
            if current_hp >= self._last_objetivo_hp:
                self._stall_turns += 1
            else:
                self._stall_turns = 0

        self._last_objetivo_hp = current_hp

        if self._stall_turns >= _STALL_THRESHOLD:
            c.draw_indicator_dot(current, 255, 0, 255)
            self._block_objetivo(c)

    # ──────────────────────────────────────────────────────────────────────────
    # Lógica de casillas adyacentes a harvesters enemigos
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_harvester_adjacents(self, c: Controller) -> list[tuple[Position, float]]:
        """
        Busca casillas cardinalmente adyacentes a harvesters enemigos en visión
        que estén vacías o solo tengan una road (aliada o enemiga).
        Devuelve lista de (pos, dist²) ordenable, excluyendo bloqueadas.
        """
        current = c.get_position()
        candidates: list[tuple[Position, float]] = []
        seen: set[Position] = set()

        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == c.get_team():
                continue
            if c.get_entity_type(bid) != EntityType.HARVESTER:
                continue


            harv_pos = c.get_position(bid)

            if c.get_tile_env(harv_pos) == Environment.ORE_AXIONITE:
                continue

            for d in _CARD_DIRS:
                adj = harv_pos.add(d)
                if adj in seen:
                    continue
                if not _is_in_bounds(c, adj):
                    continue
                if not c.is_in_vision(adj):
                    continue
                if self._is_blocked(adj):
                    continue

                seen.add(adj)

                env = c.get_tile_env(adj)
                if env == Environment.WALL:
                    continue
                if not c.is_tile_passable(adj):
                    continue
                existing = c.get_tile_building_id(adj)
                if existing is not None:
                    # Solo aceptar si es una road (aliada o enemiga)
                    if c.get_entity_type(existing) != EntityType.ROAD:
                        continue

                dist = current.distance_squared(adj)
                candidates.append((adj, dist))

        return candidates

    # ──────────────────────────────────────────────────────────────────────────
    # Lógica de "final de línea"
    # ──────────────────────────────────────────────────────────────────────────

    def _get_endpoint_info(self, c: Controller, bid: int) -> tuple[Position, bool] | None:
        """
        Para un conveyor o bridge enemigo, determina cuál es la casilla objetivo
        y si es un "destino libre" (casilla vacía/road a la que apunta) o no.
        """
        etype = c.get_entity_type(bid)
        building_pos = c.get_position(bid)

        if etype == EntityType.CONVEYOR or etype == EntityType.ARMOURED_CONVEYOR:
            direction = c.get_direction(bid)
            dest = building_pos.add(direction)
        elif etype == EntityType.BRIDGE:
            dest = c.get_bridge_target(bid)
        else:
            return None

        if dest is None or not _is_in_bounds(c, dest):
            return None

        if not c.is_in_vision(dest):
            return None

        dest_bid = c.get_tile_building_id(dest)

        if dest_bid is None:
            return (dest, True)

        dest_etype = c.get_entity_type(dest_bid)
        dest_team = c.get_team(dest_bid)

        if dest_etype == EntityType.CORE and dest_team != c.get_team():
            return (building_pos, False)

        if dest_etype in _TURRET_TYPES and dest_team != c.get_team():
            return (building_pos, False)

        if dest_etype == EntityType.ROAD:
            return (dest, True)

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Escaneo
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_enemies(self, c: Controller):
        current = c.get_position()

        # ── Validar objetivo actual ────────────────────────────────────────────
        if self.objetivo is not None:
            if c.is_in_vision(self.objetivo):
                bid = c.get_tile_building_id(self.objetivo)

                if self.objetivo_es_harvester_adj:
                    # El objetivo harvester-adj está listo cuando ya hay una torreta aliada ahí
                    if bid is not None and c.get_team(bid) == c.get_team() \
                            and c.get_entity_type(bid) in _TURRET_TYPES:
                        self.objetivo = None
                        self.pendiente_torreta = False
                        self.objetivo_es_harvester_adj = False
                    return

                if self.pendiente_torreta or self.objetivo_es_destino_libre:
                    if bid is not None and c.get_team(bid) == c.get_team() \
                            and c.get_entity_type(bid) in _TURRET_TYPES:
                        self.objetivo = None
                        self.pendiente_torreta = False
                        self.objetivo_es_destino_libre = False
                    elif self.objetivo_es_destino_libre and bid is not None \
                            and c.get_team(bid) != c.get_team():
                        self.objetivo = None
                        self.objetivo_es_destino_libre = False
                    return
                else:
                    if bid is None or c.get_team(bid) == c.get_team():
                        self.objetivo = None
                        self.objetivo_es_destino_libre = False

        # ── Prioridad 0: casillas adyacentes a harvesters enemigos ────────────
        harv_candidates = self._scan_harvester_adjacents(c)
        if harv_candidates:
            best_pos, best_dist = min(harv_candidates, key=lambda t: t[1])

            # Si ya tenemos un objetivo harvester-adj, solo reemplazar si este es más cercano
            if self.objetivo_es_harvester_adj and self.objetivo is not None:
                cur_dist = current.distance_squared(self.objetivo)
                if best_dist < cur_dist:
                    self.objetivo = best_pos
                    self.pendiente_torreta = True
                    self.objetivo_es_destino_libre = False
            else:
                self.objetivo = best_pos
                self.objetivo_es_harvester_adj = True
                self.pendiente_torreta = True
                self.objetivo_es_destino_libre = False
            return

        # Si teníamos un objetivo harvester-adj pero ya no lo vemos, limpiar
        if self.objetivo_es_harvester_adj:
            self.objetivo = None
            self.objetivo_es_harvester_adj = False
            self.pendiente_torreta = False

        # ── Recopilar candidatos de "final de línea" en visión ────────────────
        candidates_libres: list[tuple[Position, float]] = []
        candidates_destruir: list[tuple[Position, float]] = []

        _ENDPOINT_TYPES = (
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
        )

        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == c.get_team():
                continue
            if c.get_entity_type(bid) not in _ENDPOINT_TYPES:
                continue

            result = self._get_endpoint_info(c, bid)
            if result is None:
                continue

            obj_pos, es_libre = result

            if self._is_blocked(obj_pos):
                continue

            dist = current.distance_squared(obj_pos)
            if es_libre:
                candidates_libres.append((obj_pos, dist))
            else:
                candidates_destruir.append((obj_pos, dist))

        # ── Prioridad 1: destinos libres (colocar torreta directamente) ────────
        if candidates_libres:
            best_pos, best_dist = min(candidates_libres, key=lambda t: t[1])

            if self.objetivo_es_destino_libre and self.objetivo is not None:
                cur_dist = current.distance_squared(self.objetivo)
                if best_dist < cur_dist:
                    self.objetivo = best_pos
                    self.pendiente_torreta = True
            else:
                self.objetivo = best_pos
                self.objetivo_es_destino_libre = True
                self.pendiente_torreta = True
            return

        if self.objetivo_es_destino_libre:
            self.objetivo = None
            self.objetivo_es_destino_libre = False
            self.pendiente_torreta = False

        # ── Prioridad 2: estructuras a destruir (+ torreta encima) ────────────
        if self.objetivo is not None:
            if candidates_destruir:
                best_pos, best_dist = min(candidates_destruir, key=lambda t: t[1])
                if best_dist < current.distance_squared(self.objetivo):
                    self.objetivo = best_pos
                    self.pendiente_torreta = False
            return

        if candidates_destruir:
            best_pos, _ = min(candidates_destruir, key=lambda t: t[1])
            self.objetivo = best_pos
            self.objetivo_es_destino_libre = False
            self.pendiente_torreta = False

    # ──────────────────────────────────────────────────────────────────────────
    # Trabajar sobre el objetivo
    # ──────────────────────────────────────────────────────────────────────────

    def _build_turret_at(self, c: Controller, target: Position):
        """
        Construye la torreta apropiada en target según el tipo de objetivo.
        - objetivo_es_harvester_adj: siempre sentinel mirando al core enemigo.
        - Si no, lógica original (gunner/sentinel según distancia al core).
        Limpia el estado de objetivo al terminar.
        """
        if self.enemy_core_pos is not None:
            dir_to_enemy = target.direction_to(self.enemy_core_pos)
        else:
            dir_to_enemy = Direction.NORTH

        built = False

        if self.objetivo_es_harvester_adj:
            # Siempre sentinel mirando al core enemigo
            id_contigua = c.get_tile_building_id(target.add(dir_to_enemy))
            if c.get_entity_type(id_contigua) is EntityType.HARVESTER:
                dir_to_enemy = dir_to_enemy.rotate_left()
            if c.can_build_sentinel(target, dir_to_enemy):
                c.build_sentinel(target, dir_to_enemy)
                built = True
            else:
                # Intentar todas las direcciones como fallback
                for d in _ALL_DIRS:
                    if c.can_build_sentinel(target, d):
                        c.build_sentinel(target, d)
                        built = True
                        break
        elif self.enemy_core_pos is not None:
            dist_to_enemy = target.distance_squared(self.enemy_core_pos)
            if dist_to_enemy <= 32 and dist_to_enemy > 13:
                if c.can_build_sentinel(target, dir_to_enemy):
                    c.build_sentinel(target, dir_to_enemy)
                    built = True
            else:
                if c.can_build_gunner(target, dir_to_enemy):
                    c.build_gunner(target, dir_to_enemy)
                    built = True
        else:
            if c.can_build_gunner(target, dir_to_enemy):
                c.build_gunner(target, dir_to_enemy)
                built = True
            else:
                for d in _ALL_DIRS:
                    if c.can_build_gunner(target, d):
                        c.build_gunner(target, d)
                        built = True
                        break

        if built:
            self.objetivo = None
            self.pendiente_torreta = False
            self.objetivo_es_destino_libre = False
            self.objetivo_es_harvester_adj = False

    def _work_objetivo(self, c: Controller):
        current = c.get_position()
        target = self.objetivo

        # Acercarse si no está en visión
        if not c.is_in_vision(target):
            self._navigate_to(c, target)
            return

        bid = c.get_tile_building_id(target)

        # ── Objetivo cumplido: ya hay torreta aliada ──────────────────────────
        if (bid is not None
                and c.get_team(bid) == c.get_team()
                and c.get_entity_type(bid) in _TURRET_TYPES):
            self.objetivo = None
            self.pendiente_torreta = False
            self.objetivo_es_destino_libre = False
            self.objetivo_es_harvester_adj = False
            return

        # ── Objetivo imposible: edificio enemigo no passable ──────────────────
        if (bid is not None
                and c.get_team(bid) != c.get_team()
                and not c.is_tile_passable(target)):
            self.objetivo = None
            self.pendiente_torreta = False
            self.objetivo_es_destino_libre = False
            self.objetivo_es_harvester_adj = False
            return

        # ── Acercarse al objetivo ─────────────────────────────────────────────
        if current.distance_squared(target) > 2:
            self._navigate_to(c, target)
            return

        # ── Limpiar la casilla si hace falta ─────────────────────────────────
        if not self._clear_tile(c, target):
            return

        # ── Casilla libre: construir torreta ──────────────────────────────────
        # Salir de encima si estamos justo en target
        if current == target:
            for d in _ALL_DIRS:
                adj = target.add(d)
                if _is_in_bounds(c, adj) and self._try_move(c, d):
                    return
            return

        self._build_turret_at(c, target)

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
                self.has_seen_enemy_core = True
                break
    
    def go_to_enemy_core(self, c: Controller):
        current = c.get_position()
        dir = self.navegador.moveTo(c, self.enemy_core_pos, False)
        nextpos = current.add(dir)
        c.draw_indicator_line(current, self.enemy_core_pos, 255, 140, 0)
        if c.can_build_road(nextpos):
            c.build_road(nextpos)
        if c.can_move(dir):
            c.move(dir)
        
        for b in c.get_nearby_buildings():
            if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
                self.has_seen_enemy_core = True
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

    # ──────────────────────────────────────────────────────────────────────────
    # Revisar si hay bots enemigos al rededor de un bot aliado
    # ──────────────────────────────────────────────────────────────────────────

    def hay_enemigo_adyacente(self, c: Controller) -> bool:
        current = c.get_position()

        for d in _ALL_DIRS:
            casilla_adyacente = current.add(d)
            if _is_in_bounds(c, casilla_adyacente) and c.is_in_vision(casilla_adyacente):
                bot = c.get_tile_building_id(casilla_adyacente)
                if bot is not None:
                    hay_bot = (c.get_entity_type(bot) == EntityType.BUILDER_BOT
                               and c.get_team(bot) != c.get_team())
                    if hay_bot:
                        return True
        return False

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        building_id = c.get_tile_building_id(target)
        if building_id is None:
            return True

        current = c.get_position()
        is_ally = c.get_team(building_id) == c.get_team()

        if is_ally:
            if c.can_destroy(target):
                c.destroy(target)
                return True
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return False
        else:
            if current == target:
                if c.can_fire(target):
                    c.fire(target)
                    return c.get_tile_building_id(target) is None
                return False
            else:
                if c.is_tile_passable(target):
                    dir = self.navegador.moveTo(c, target, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    self._try_move(c, dir)
                return False

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not _is_in_bounds(c, dest):
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False