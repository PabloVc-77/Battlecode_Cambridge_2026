"""
builderAtaque_caminos.py
========================
Bot híbrido: fase de exploración para localizar el core enemigo (igual que
AtaqueCaminos), seguida de una fase de construcción de cadenas de recursos
hacia la base enemiga (lógica de builder.py), con estas diferencias clave:

1. DESTINO DE LAS CADENAS
   Los `end_bridges` que se usan como nodos base son posiciones alrededor del
   core enemigo (espejo de los end_bridges propios), en vez de alrededor del
   core aliado.

2. FIN DE CADENA = SENTINEL
   Cuando el modo 2 (bridgeHome) calcularía el siguiente puente y la casilla
   candidata está a distancia² ≤ 32 del core enemigo (rango de sentinel),
   en lugar de construir un puente coloca allí un sentinel apuntando al core
   enemigo y reinicia el flujo completo desde el modo 0.

3. ACTIVACIÓN DEL MODO 5 (defensa con sentinel)
   Se activa igual que en builder.py al ver una torreta enemiga, Y TAMBIÉN
   si se detectan más de 4 estructuras enemigas visibles que no sean ROAD ni
   MARKER.

4. El resto de la lógica (modos 0-6, conveyors, reparación de cadenas…)
   es idéntica a builder.py.
"""

from cambc import (
    Controller, Direction, EntityType, Environment,
    Position, ResourceType,
)
import math
import bignav_a_mem as bugnav

from botRolex.helper.layout_defensivo import compute_layout_for_core

# ── Sentinel attack radius² (GameConstants.SENTINEL_VISION_RADIUS_SQ = 32) ──
_SENTINEL_RANGE_SQ = 32

# ── Estructuras "de combate / logística pesada" enemigas que cuentan como
#    amenaza cuando hay más de 4 de ellas visibles ─────────────────────────────
_HEAVY_ENEMY_TYPES = frozenset({
    EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH,
    EntityType.LAUNCHER, EntityType.FOUNDRY, EntityType.HARVESTER,
    EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE,
    EntityType.SPLITTER, EntityType.BARRIER,
})

# ─────────────────────────────────────────────────────────────────────────────
# Helpers (copiados de builder.py sin cambios)
# ─────────────────────────────────────────────────────────────────────────────

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return 0 <= pos.x < w and 0 <= pos.y < h


def revisor_casillas_extractor(c: Controller, pos: Position):
    Existe = False
    casillas = [
        pos.add(Direction.NORTH), pos.add(Direction.EAST),
        pos.add(Direction.SOUTH), pos.add(Direction.WEST),
    ]
    for casilla in casillas:
        if _is_in_bounds(c, casilla):
            if c.is_in_vision(casilla):
                building_id = c.get_tile_building_id(casilla)
                if (building_id is not None
                        and c.get_entity_type(building_id) in TRANSPORT_TYPES
                        and c.get_team(building_id) == c.get_team()):
                    Existe = True
                    break
            else:
                Existe = True
                break
    return Existe


TRANSPORT_TYPES = (
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
)

# ── Axionite bridge marker encoding ──────────────────────────────────────────
_AXIONITE_MARKER_IDENT = 833
_WIP_MARKER_IDENT = 999


def _encode_wip_marker(bot_id: int) -> int:
    return _WIP_MARKER_IDENT * 10000 + bot_id


def _is_wip_marker(value: int) -> bool:
    return value // 10000 == _WIP_MARKER_IDENT


def _is_wip_placeholder(c: Controller, bid: int) -> bool:
    if bid is None or c.get_team(bid) != c.get_team():
        return False
    etype = c.get_entity_type(bid)
    if etype == EntityType.MARKER:
        try:
            return _is_wip_marker(c.get_marker_value(bid))
        except Exception:
            return False
    if etype == EntityType.BARRIER:
        return True
    if etype in (EntityType.SENTINEL, EntityType.GUNNER, EntityType.BREACH):
        return True
    return False


def _place_wip_marker(c: Controller, pos: Position) -> bool:
    if not c.is_in_vision(pos):
        return False
    bid = c.get_tile_building_id(pos)
    if _is_wip_placeholder(c, bid):
        return True
    if c.can_place_marker(pos):
        c.place_marker(pos, _encode_wip_marker(c.get_id()))
        return True
    return False


def _get_wip_marker_id(value: int) -> int:
    return value % 10000


def _encode_axionite_marker(pos: Position) -> int:
    return _AXIONITE_MARKER_IDENT * 10000 + pos.x * 100 + pos.y


def _is_axionite_marker(value: int) -> bool:
    return value // 10000 == _AXIONITE_MARKER_IDENT


def _decode_axionite_marker_pos(value: int) -> Position:
    remainder = value % 10000
    return Position(remainder // 100, remainder % 100)


def _bridge_is_axionite_tagged(c: Controller, bridge_pos: Position) -> bool:
    for check in [
        bridge_pos.add(Direction.NORTH), bridge_pos.add(Direction.EAST),
        bridge_pos.add(Direction.SOUTH), bridge_pos.add(Direction.WEST),
        bridge_pos.add(Direction.NORTHEAST), bridge_pos.add(Direction.NORTHWEST),
        bridge_pos.add(Direction.SOUTHEAST), bridge_pos.add(Direction.SOUTHWEST),
    ]:
        if not _is_in_bounds(c, check):
            continue
        if not c.is_in_vision(check):
            continue
        mid = c.get_tile_building_id(check)
        if (mid is not None
                and c.get_entity_type(mid) == EntityType.MARKER
                and c.get_team(mid) == c.get_team()):
            val = c.get_marker_value(mid)
            if _is_axionite_marker(val) and _decode_axionite_marker_pos(val) == bridge_pos:
                return True
    return False


def _is_conv_better(
    c: Controller, ini: Position, end: Position,
    layout, entity_end: EntityType, direction_end: Direction,
):
    conveyor_cost = c.get_conveyor_cost()[0]
    bridge_cost   = c.get_bridge_cost()[0]

    from collections import deque
    queue = deque()
    queue.append((ini, []))
    visited = {ini}

    while queue:
        current, path = queue.popleft()
        i = len(path) + 1
        if 1.1 * i * conveyor_cost >= bridge_cost:
            return None

        for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
            neighbor = current.add(d)
            if neighbor in visited:
                continue
            if not _is_in_bounds(c, neighbor):
                continue
            if not c.is_in_vision(neighbor):
                continue
            if neighbor in layout and neighbor != end:
                continue
            if neighbor in TRANSPORT_TYPES and neighbor != end:
                continue

            env = c.get_tile_env(neighbor)
            if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE, Environment.WALL):
                continue

            building_id = c.get_tile_building_id(neighbor)
            if building_id is not None:
                entity = c.get_entity_type(building_id)
                if entity == EntityType.ROAD:
                    pass
                elif (not (c.is_tile_passable(neighbor) and c.get_tile_builder_bot_id(neighbor) is None)
                      and (entity != EntityType.BARRIER or c.get_team() != c.get_team(building_id))):
                    if neighbor != c.get_position() and entity not in TRANSPORT_TYPES:
                        continue
                elif (entity in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR, EntityType.BRIDGE)
                      and c.get_team() == c.get_team(building_id)):
                    if neighbor != end:
                        continue
                elif entity == EntityType.SPLITTER and c.get_team() == c.get_team(building_id):
                    if neighbor != end or d != c.get_direction(building_id):
                        continue

            if neighbor == end and entity_end == EntityType.SPLITTER and d != direction_end:
                continue

            new_path = path + [(current, d)]
            if neighbor == end:
                return new_path
            visited.add(neighbor)
            queue.append((neighbor, new_path))

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Clase principal
# ─────────────────────────────────────────────────────────────────────────────

class BuilderAtaqueCaminos:
    """
    Fases:
      A) Búsqueda del core enemigo (igual que AtaqueCaminos).
      B) Una vez visto el core enemigo, construir cadenas de recursos con la
         lógica de builder.py pero hacia el core enemigo, terminando con un
         sentinel cuando se alcanza el rango de disparo.
    """

    def __init__(self, c: Controller):
        # ── Navegación ────────────────────────────────────────────────────────
        self.navegador = bugnav.BugNav()

        # ── Geometría del mapa ────────────────────────────────────────────────
        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        # ── Core aliado ───────────────────────────────────────────────────────
        self.spawn: Position | None = None

        # ── Core enemigo ──────────────────────────────────────────────────────
        self.enemy_core_pos:        Position | None = None
        self.enemy_core_candidates: list[Position]  = []
        self.simetry:               int             = 0
        self.has_seen_enemy_core:   bool            = False

        # ── Endpoints de destino (alrededor del core enemigo) ─────────────────
        # Se calculan una vez que conocemos enemy_core_pos.
        self.end_bridges_titanium: list[Position] = []
        self.end_bridges_axionite: list[Position] = []

        # ── Layout del core aliado (para no pisarlo) ───────────────────────────
        self.layout_pos:    set[Position] = set()
        self.layot_entity:  list          = []

        # ── Estado del builder (copiado de builder.py) ────────────────────────
        self.objetivos:      list[Position] = []
        self.objetivos_set:  set[Position]  = set()
        self.recolectores:   list[Position] = []
        self.recolectores_set: set[Position] = set()

        self.current_target:  Position | None = None
        self.conveyor_path:   list             = []
        self.mode_after_conv: int              = 2

        self.mode = 0
        #   0: buscar ore
        #   1: colocar bridge junto al ore
        #   2: ir hacia la base (enemiga)
        #   3: revisar estructura
        #   4: colocar conveyors
        #   5: defender con sentinel
        #   6: reparar cadena rota

        self.last_bridge_end:       Position | None = None
        self.last_bridge_built_pos: Position | None = None
        self.last_conveyor_pos:     Position | None = None
        self.last_path_built:       Position | None = None
        self.last_conveyor_dir:     Direction | None = None
        self.check_pos:             Position | None = None

        self.bridge_origin:      Position | None = None
        self.bridge_destination: Position | None = None

        self.is_axionite_path:        bool            = False
        self.pending_axionite_marker: Position | None = None

        self.titanium_harvesters: set[Position] = set()
        self.banned_ores:         set[Position] = set()

        self._repair_broken_pos: Position | None = None
        self._repair_chain_pos:  Position | None = None
        self._repair_harvester:  Position | None = None

        self._mode5_prev_mode:    int              = 2
        self._mode5_threat_pos:   Position | None  = None
        self._mode5_sentinel_pos: Position | None  = None
        self._mode5_gone_since:   int              = 0
        self._mode5_absent_turns: int              = 0
        self._mode5_barrier_pos:  Position | None  = None

        self._connected_cache: dict = {}
        self.reserved: bool = False

        self.turret_places: list = []

        # ── Detección del core aliado ─────────────────────────────────────────
        builds = c.get_nearby_buildings()
        for b in builds:
            if (c.get_entity_type(b) == EntityType.CORE
                    and c.get_team(b) == c.get_team()):
                self.spawn = c.get_position(b)
                break

        if self.spawn is not None:
            self._init_enemy_candidates()
            layout = compute_layout_for_core(c, self.spawn)
            self.layout_pos   = layout['layout_positions']
            self.layot_entity = layout['layout']

    # ──────────────────────────────────────────────────────────────────────────
    # Inicialización de candidatos simétricos
    # ──────────────────────────────────────────────────────────────────────────

    def _init_enemy_candidates(self):
        if self.spawn is None:
            return
        x, y = self.spawn.x, self.spawn.y
        w, h = self.map_w, self.map_h
        self.enemy_core_candidates = [
            Position(w - 1 - x, y),
            Position(x, h - 1 - y),
            Position(w - 1 - x, h - 1 - y),
        ]

    def _init_enemy_endpoints(self, c: Controller):
        """
        Calcula los endpoints de destino alrededor del core enemigo.
        Son equivalentes a los end_bridges del core aliado en builder.py,
        pero centrados en el core enemigo. Se usan como nodos base a los que
        hay que llegar con la cadena de transporte.
        """
        s = self.enemy_core_pos
        if s is None:
            return
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
        valid = []
        for v in candidates:
            if self._in_bounds(v):
                env = c.get_tile_env(v) if c.is_in_vision(v) else None
                if env != Environment.WALL:
                    valid.append(v)
        # Para este bot todos los endpoints son "titanium" (sin distinción axionita
        # en la fase de ataque, solo queremos llegar al core enemigo).
        self.end_bridges_titanium = valid
        self.end_bridges_axionite = valid  # mismos endpoints para ambos tipos

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers de bounds / movimiento
    # ──────────────────────────────────────────────────────────────────────────

    def _in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not self._in_bounds(dest):
            return False
        if c.can_move(direction):
            c.move(direction)
            return True
        return False

    @property
    def _active_ends(self) -> list:
        if self.is_axionite_path:
            return self.end_bridges_axionite
        return self.end_bridges_titanium if self.end_bridges_titanium else list(self.layout_pos)

    # ──────────────────────────────────────────────────────────────────────────
    # Detección de amenazas (ampliada respecto a builder.py)
    # ──────────────────────────────────────────────────────────────────────────

    def _find_enemy_threat(self, c: Controller) -> "Position | None":
        """
        Devuelve posición de amenaza si:
          a) Hay una torreta enemiga visible, O
          b) Hay más de 4 estructuras enemigas visibles que no sean ROAD ni MARKER.
        """
        turret_types = (
            EntityType.GUNNER, EntityType.SENTINEL,
            EntityType.BREACH, EntityType.LAUNCHER,
        )
        heavy_count = 0
        first_turret: Position | None = None

        for eid in c.get_nearby_entities():
            if c.get_team(eid) == c.get_team():
                continue
            et = c.get_entity_type(eid)
            if et in turret_types:
                if first_turret is None:
                    first_turret = c.get_position(eid)
            if et in _HEAVY_ENEMY_TYPES:
                heavy_count += 1

        if first_turret is not None:
            return first_turret
        if heavy_count > 4:
            # Devolver la posición de la estructura más cercana
            current = c.get_position()
            best_pos: Position | None = None
            best_d   = 10**9
            for eid in c.get_nearby_entities():
                if c.get_team(eid) == c.get_team():
                    continue
                et = c.get_entity_type(eid)
                if et in _HEAVY_ENEMY_TYPES:
                    p = c.get_position(eid)
                    d = current.distance_squared(p)
                    if d < best_d:
                        best_d   = d
                        best_pos = p
            return best_pos
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Comprobación de rango de sentinel al core enemigo
    # ──────────────────────────────────────────────────────────────────────────

    def _in_sentinel_range_of_enemy_core(self, pos: Position) -> bool:
        """
        Devuelve True si desde `pos` un sentinel puede disparar al core enemigo
        (distancia² ≤ 32 al centro del core enemigo).
        """
        if self.enemy_core_pos is None:
            return False
        return pos.distance_squared(self.enemy_core_pos) <= _SENTINEL_RANGE_SQ

    def _try_place_attack_sentinel(self, c: Controller, pos: Position) -> bool:
        """
        Intenta construir un sentinel en `pos` apuntando al core enemigo.
        Devuelve True si el sentinel quedó colocado (o ya existía).
        """
        if self.enemy_core_pos is None:
            return False
        current = c.get_position()

        # Acercarnos si hace falta
        if current.distance_squared(pos) > 2:
            d = self.navegador.moveTo(c, pos, four_dirs=False)
            next_pos = current.add(d)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, d)
            return False

        if current == pos:
            d = self.navegador._any_free_dir(c, False, self.map_w, self.map_h)
            next_pos = current.add(d)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, d)
            return False

        # Limpiar la casilla si tiene algo
        if c.is_in_vision(pos):
            bid = c.get_tile_building_id(pos)
            if bid is not None:
                et  = c.get_entity_type(bid)
                tm  = c.get_team(bid)
                if et == EntityType.SENTINEL and tm == c.get_team():
                    return True  # ya hay un sentinel aliado aquí
                if not self._clear_tile(c, pos):
                    return False

        # Elegir dirección del sentinel (la que apunta al core enemigo)
        dir_to_core = pos.direction_to(self.enemy_core_pos)
        # Verificar que puede disparar en esa dirección
        for d_try in [
            dir_to_core,
            dir_to_core.rotate_left(),
            dir_to_core.rotate_right(),
            dir_to_core.rotate_left().rotate_left(),
            dir_to_core.rotate_right().rotate_right(),
        ]:
            if c.can_fire_from(pos, d_try, EntityType.SENTINEL, self.enemy_core_pos):
                if c.can_build_sentinel(pos, d_try):
                    c.build_sentinel(pos, d_try)
                    return True
                break

        return False

    def _full_reset(self):
        """Reinicia el estado del builder para empezar una nueva cadena desde 0."""
        self.mode               = 0
        self.current_target     = None
        self.last_bridge_end    = None
        self.last_bridge_built_pos = None
        self.last_conveyor_pos  = None
        self.last_path_built    = None
        self.last_conveyor_dir  = None
        self.check_pos          = None
        self.bridge_origin      = None
        self.bridge_destination = None
        self.conveyor_path      = []
        self.is_axionite_path   = False
        self.pending_axionite_marker = None
        self._repair_broken_pos = None
        self._repair_chain_pos  = None
        self._repair_harvester  = None

    

    # ──────────────────────────────────────────────────────────────────────────
    # FASE A: Localizar core enemigo
    # ──────────────────────────────────────────────────────────────────────────

    def _find_enemy_core(self, c: Controller):
        if not self.enemy_core_candidates:
            return
        target  = self.enemy_core_candidates[self.simetry % len(self.enemy_core_candidates)]
        current = c.get_position()
        c.draw_indicator_line(current, target, 255, 140, 0)
        self._navigate_to(c, target)

        if c.is_in_vision(target):
            bid = c.get_tile_building_id(target)
            if (bid is not None
                    and c.get_entity_type(bid) == EntityType.CORE
                    and c.get_team(bid) != c.get_team()):
                self.enemy_core_pos = target
            else:
                self.simetry += 1

        for b in c.get_nearby_buildings():
            if (c.get_entity_type(b) == EntityType.CORE
                    and c.get_team(b) != c.get_team()):
                self.enemy_core_pos    = c.get_position(b)
                self.has_seen_enemy_core = True
                break

    def _go_to_enemy_core(self, c: Controller):
        current = c.get_position()
        d       = self.navegador.moveTo(c, self.enemy_core_pos, False)
        nextpos = current.add(d)
        c.draw_indicator_line(current, self.enemy_core_pos, 255, 140, 0)
        if c.can_build_road(nextpos):
            c.build_road(nextpos)
        if c.can_move(d):
            c.move(d)
        for b in c.get_nearby_buildings():
            if (c.get_entity_type(b) == EntityType.CORE
                    and c.get_team(b) != c.get_team()):
                self.has_seen_enemy_core = True
                break

    def _navigate_to(self, c: Controller, dest: Position):
        current = c.get_position()
        d       = self.navegador.moveTo(c, dest, four_dirs=False)
        next_pos = current.add(d)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(d):
            c.move(d)

    # ──────────────────────────────────────────────────────────────────────────
    # FASE B — MODO 0: Buscar ore
    # ──────────────────────────────────────────────────────────────────────────

    def _has_viable_adjacent(self, c: Controller, tile: Position) -> bool:
        for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
            adj = tile.add(d)
            if not self._in_bounds(adj):
                continue
            if c.is_in_vision(adj):
                env = c.get_tile_env(adj)
                if env == Environment.WALL:
                    continue
                bid = c.get_tile_building_id(adj)
                if bid is None:
                    return True
                if c.is_tile_passable(adj):
                    return True
            else:
                return True
        return False

    def oreCerca(self, c: Controller):
        lista   = c.get_nearby_tiles()
        changed = False
        for tile in lista:
            if tile in self.banned_ores:
                continue
            env = c.get_tile_env(tile)
            es_mineral = (
                env == Environment.ORE_TITANIUM
                or (env == Environment.ORE_AXIONITE
                    and c.get_global_resources()[1] < 533
                    and len(self.titanium_harvesters) > 1)
            )
            if es_mineral:
                if not self._has_viable_adjacent(c, tile):
                    self.banned_ores.add(tile)
                    if tile in self.objetivos_set:
                        self.objetivos.remove(tile)
                        self.objetivos_set.discard(tile)
                        changed = True
                    if tile in self.recolectores_set:
                        self.recolectores.remove(tile)
                        self.recolectores_set.discard(tile)
                    continue

                building_id = c.get_tile_building_id(tile)
                if building_id is not None:
                    entity = c.get_entity_type(building_id)
                    team   = c.get_team() == c.get_team(building_id)
                    if entity == EntityType.HARVESTER:
                        flag = revisor_casillas_extractor(c, tile)
                        if env == Environment.ORE_TITANIUM and flag:
                            self.titanium_harvesters.add(tile)
                        if tile in self.objetivos_set:
                            self.objetivos.remove(tile)
                            self.objetivos_set.discard(tile)
                            changed = True
                        if not flag:
                            if tile not in self.recolectores_set:
                                self.recolectores.append(tile)
                                self.recolectores_set.add(tile)
                        else:
                            if tile in self.recolectores_set:
                                self.recolectores.remove(tile)
                                self.recolectores_set.discard(tile)
                        continue
                    elif entity == EntityType.MARKER and team:
                        value = c.get_marker_value(building_id)
                        if value != c.get_id():
                            if tile in self.recolectores_set:
                                self.recolectores.remove(tile)
                                self.recolectores_set.discard(tile)
                            if tile in self.objetivos_set:
                                self.objetivos.remove(tile)
                                self.objetivos_set.discard(tile)
                                changed = True
                            continue
                    elif entity in TRANSPORT_TYPES and team:
                        if tile in self.recolectores_set:
                            self.recolectores.remove(tile)
                            self.recolectores_set.discard(tile)
                        if tile in self.objetivos_set:
                            self.objetivos.remove(tile)
                            self.objetivos_set.discard(tile)
                            changed = True
                        continue
                    else:
                        if not (
                            (c.is_tile_passable(tile) or c.get_position() == tile)
                            or (entity == EntityType.BARRIER and not team)
                        ):
                            if tile in self.recolectores_set:
                                self.recolectores.remove(tile)
                                self.recolectores_set.discard(tile)
                            if tile in self.objetivos_set:
                                self.objetivos.remove(tile)
                                self.objetivos_set.discard(tile)
                                changed = True
                            continue

                if tile not in self.objetivos_set:
                    self.objetivos.append(tile)
                    self.objetivos_set.add(tile)
                    changed = True
            else:
                if tile in self.objetivos_set:
                    self.objetivos.remove(tile)
                    self.objetivos_set.discard(tile)
                    changed = True

        if changed:
            current = c.get_position()
            self.objetivos.sort(key=lambda p: current.distance_squared(p))

    def buscar_material(self, c: Controller, current: Position):
        broken = self._scan_broken_chains(c)
        if broken is not None:
            broken_pos, upstream_pos   = broken
            self._repair_broken_pos    = broken_pos
            self._repair_chain_pos     = upstream_pos
            self._repair_harvester     = None
            self.mode = 6
            self.repair_broken_chain(c)
            return

        self.oreCerca(c)
        target = None
        entityID = c.get_tile_building_id(current)
        if entityID is not None:
            tileTeam = c.get_team(entityID)
            if tileTeam != c.get_team() and c.get_entity_type(entityID) in TRANSPORT_TYPES:
                if c.can_fire(current):
                    c.fire(current)
                return

        if self.objetivos and self.current_target is None:
            target = self.objetivos[0]
        elif self.recolectores and self.current_target is None:
            target = self.recolectores[0]

        if target is not None:
            c.draw_indicator_line(current, target, 204, 39, 245)
            if c.is_in_vision(target):
                build_id = c.get_tile_building_id(target)
                if (build_id is not None
                        and c.get_entity_type(build_id) != EntityType.HARVESTER
                        and not self._clear_tile(c, target)):
                    return

            if c.can_place_marker(target):
                c.place_marker(target, c.get_id())
                self.reserved       = True
                self.current_target = target

            if c.can_build_harvester(target):
                c.build_harvester(target)
                self.current_target = target
                if target in self.objetivos_set:
                    self.objetivos.remove(target)
                    self.objetivos_set.discard(target)
                self.is_axionite_path = (c.get_tile_env(target) == Environment.ORE_AXIONITE)
                self.mode = 1
            elif current == target:
                for d in Direction:
                    if d == Direction.CENTRE:
                        continue
                    adj = target.add(d)
                    if self._in_bounds(adj) and self._try_move(c, d):
                        break
            elif current.distance_squared(target) > 2:
                siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
                move_pos = current.add(siguiente_dir)
                c.draw_indicator_line(current, move_pos, 66, 245, 39)
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)
                if current.add(siguiente_dir).distance_squared(target) != 0:
                    self._try_move(c, siguiente_dir)
            else:
                b_id = c.get_tile_building_id(target)
                if (b_id is not None
                        and c.get_entity_type(b_id) == EntityType.HARVESTER
                        and not revisor_casillas_extractor(c, c.get_position(b_id))):
                    self.current_target = target
                    if target in self.objetivos_set:
                        self.objetivos.remove(target)
                        self.objetivos_set.discard(target)
                    if target in self.recolectores_set:
                        self.recolectores.remove(target)
                        self.recolectores_set.discard(target)
                    self.is_axionite_path = (c.get_tile_env(target) == Environment.ORE_AXIONITE)
                    self.mode = 1
                    return
                if target in self.objetivos_set:
                    self.objetivos.remove(target)
                    self.objetivos_set.discard(target)
                self.current_target = None
        else:
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            self._try_move(c, move_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # MODO 1: Colocar bridge junto al ore
    # ──────────────────────────────────────────────────────────────────────────

    def place_bridge_ore(self, c: Controller):
        places      = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
        active_ends = self._active_ends
        self.reserved = False

        if revisor_casillas_extractor(c, self.current_target):
            self.mode = 3
            for d in places:
                spot = self.current_target.add(d)
                if _is_in_bounds(c, spot) and c.is_in_vision(spot):
                    b_id = c.get_tile_building_id(spot)
                    if b_id is not None:
                        entity = c.get_entity_type(b_id)
                        if entity == EntityType.BRIDGE:
                            self.last_bridge_end = c.get_bridge_target(b_id)
                        elif entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                            self.last_bridge_end = self.current_target.add(c.get_direction(b_id))
            if self.last_bridge_end is not None:
                self.revisar_camino_casa(c)
                return

        viable_places           = []
        extra_places_for_turrent = []
        for d in places:
            spot = self.current_target.add(d)
            if self._in_bounds(spot) and c.is_in_vision(spot):
                something  = c.get_tile_building_id(spot)
                something2 = c.get_tile_env(spot)
                if (
                    (something is None or c.is_tile_passable(spot)
                     or spot == c.get_position()
                     or c.get_entity_type(something) == EntityType.MARKER)
                    and something2 != Environment.WALL
                ):
                    if something is not None and c.get_team() == c.get_team(something):
                        etype = c.get_entity_type(something)
                        if etype == EntityType.MARKER:
                            if _get_wip_marker_id(c.get_marker_value(something)) == c.get_id():
                                viable_places.insert(0, spot)
                                break
                            else:
                                self.current_target     = None
                                self.mode               = 0
                                self.last_bridge_built_pos = None
                                self.last_conveyor_pos  = None
                                self.last_path_built    = None
                                return
                    if something2 not in [Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]:
                        viable_places.append(spot)
                    else:
                        extra_places_for_turrent.append(spot)
                elif (something is not None
                      and c.get_entity_type(something) == EntityType.BARRIER
                      and c.get_team() == c.get_team(something)):
                    viable_places.append(spot)

        if not viable_places:
            if not extra_places_for_turrent:
                self.current_target     = None
                self.mode               = 0
                self.last_bridge_built_pos = None
                self.last_conveyor_pos  = None
                self.last_path_built    = None
                return
            viable_places = extra_places_for_turrent

        current = c.get_position()
        # Ordenar por distancia al core enemigo (queremos llegar a él)
        viable_places.sort(key=lambda p: (
            self.enemy_core_pos.distance_squared(p)
            if self.enemy_core_pos else self.spawn.distance_squared(p)
        ))
        place = viable_places[0]
        c.draw_indicator_dot(place, 0, 0, 0)

        if place in active_ends:
            self.current_target     = None
            self.mode               = 0
            self.last_bridge_built_pos = None
            self.last_conveyor_pos  = None
            self.last_path_built    = None
            return

        if c.is_in_vision(place):
            if not self._clear_tile(c, place):
                return

        if place == current:
            d        = self.navegador._any_free_dir(c, False, self.map_w, self.map_h)
            move_pos = current.add(d)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            self._try_move(c, d)
            return

        if current.distance_squared(place) > 2:
            d        = self.navegador.moveTo(c, place, False)
            move_pos = current.add(d)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            self._try_move(c, d)
            return

        nearby_builds = c.get_nearby_buildings()

        if self.bridge_destination is not None:
            end = self.bridge_destination
        else:
            target_end = self._find_best_bridge_end(place, c, nearby_builds)
            end = target_end
            if target_end is None:
                self.mode               = 0
                self.current_target     = None
                self.last_bridge_built_pos = None
                self.last_conveyor_pos  = None
                self.last_path_built    = None
                return

            if not self.is_axionite_path:
                conv_path = _is_conv_better(
                    c, place, target_end,
                    self.layout_pos,
                    self.layot_entity[2] if len(self.layot_entity) > 2 else EntityType.CONVEYOR,
                    self.layot_entity[4] if len(self.layot_entity) > 4 else Direction.NORTH,
                )
                self.conveyor_path = conv_path
                if conv_path:
                    conv_pos, conv_dir = conv_path[0]
                    if c.can_build_armoured_conveyor(conv_pos, conv_dir):
                        c.build_armoured_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end  = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    elif c.can_build_conveyor(conv_pos, conv_dir):
                        c.build_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end  = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    else:
                        self._try_mark_path_wip(c, conv_pos)
                    self.mode = 4
                    return

            c.draw_indicator_dot(target_end, 255, 255, 255)

        c.draw_indicator_dot(end, 255, 255, 255)

        building_id_place = c.get_tile_building_id(place)
        if (building_id_place is not None
                and c.get_entity_type(building_id_place) == EntityType.BARRIER
                and c.get_team(building_id_place) == c.get_team()):
            if c.can_destroy(place):
                c.destroy(place)

        if c.can_build_bridge(place, end):
            c.build_bridge(place, end)
            self.last_path_built       = place
            self.last_bridge_end       = end
            self.last_bridge_built_pos = place
            self.bridge_destination    = None
            self.bridge_origin         = None
            if self.is_axionite_path:
                self.pending_axionite_marker = place
            if end in active_ends:
                self._full_reset()
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end))
                  in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR)
                  and c.get_team() == c.get_team(c.get_tile_building_id(end))):
                self.mode = 3
            else:
                self.mode = 2
        else:
            if self._try_mark_path_wip(c, place):
                if c.is_in_vision(place):
                    mark = c.get_tile_building_id(place)
                    val  = c.get_marker_value(mark)
                    if c.get_id() != _get_wip_marker_id(val):
                        self.current_target     = None
                        self.mode               = 0
                        self.last_bridge_built_pos = None
                        self.last_conveyor_pos  = None
                        self.last_path_built    = None

    # ──────────────────────────────────────────────────────────────────────────
    # MODO 2: Avanzar hacia la base enemiga (bridgeHome modificado)
    # ──────────────────────────────────────────────────────────────────────────

    def bridgeHome(self, c: Controller):
        current    = c.get_position()
        bridge_end = self.last_bridge_end

        # ── Detección de torreta enemiga en la siguiente casilla ──────────────
        if bridge_end is not None and c.is_in_vision(bridge_end) and not self.is_axionite_path:
            next_bid = c.get_tile_building_id(bridge_end)
            if (next_bid is not None
                    and c.get_entity_type(next_bid) in (
                        EntityType.GUNNER, EntityType.SENTINEL,
                        EntityType.BREACH, EntityType.LAUNCHER)
                    and c.get_team(next_bid) != c.get_team()):
                threat = self._find_enemy_threat(c)
                if threat is not None:
                    self.last_bridge_end         = self.last_path_built
                    self._mode5_prev_mode        = self.mode
                    self._mode5_threat_pos       = threat
                    self._mode5_absent_turns     = 0
                    self._mode5_gone_since       = 0
                    self._mode5_sentinel_pos     = None
                    self.mode = 5
                    self.defend_sentinel(c)
                    return

        if bridge_end is not None and c.is_in_vision(bridge_end):
            next_bid = c.get_tile_building_id(bridge_end)
            if (next_bid is not None
                    and c.get_team() == c.get_team(next_bid)
                    and c.get_entity_type(next_bid) in TRANSPORT_TYPES):
                self.mode = 3
                return

        active_ends  = self._active_ends
        self.reserved = False

        if bridge_end is not None and bridge_end in active_ends:
            self._full_reset()
            return

        # Moverse hasta el anchor
        if bridge_end is not None and current != bridge_end and current.distance_squared(bridge_end) > 2:
            d        = self.navegador.moveTo(c, bridge_end, four_dirs=False)
            next_pos = current.add(d)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, d)
            return

        if bridge_end is None:
            # Sin anchor, ir hacia el core enemigo
            d = self.navegador.moveTo(c, self.enemy_core_pos, four_dirs=False)
            next_pos = current.add(d)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, d)
            return

        nearby_builds = c.get_nearby_buildings()

        if self.bridge_destination is not None:
            end = self.bridge_destination
        else:
            target_end = self._find_best_bridge_end(bridge_end, c, nearby_builds)

            if target_end is None:
                d = self.navegador.moveTo(c, self.enemy_core_pos, four_dirs=False)
                next_pos = current.add(d)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, d)
                return

            # ── MODIFICACIÓN CLAVE: ¿estamos en rango de sentinel? ───────────
            # Si target_end (o bridge_end) ya está en rango de sentinel del core
            # enemigo, colocamos el sentinel aquí y reiniciamos.
            if self._in_sentinel_range_of_enemy_core(bridge_end):
                placed = self._try_place_attack_sentinel(c, bridge_end)
                if placed:
                    self._full_reset()
                return

            c.draw_indicator_dot(target_end, 255, 255, 0)

            if not self.is_axionite_path:
                conv_path = _is_conv_better(
                    c, bridge_end, target_end,
                    self.layout_pos,
                    self.layot_entity[2] if len(self.layot_entity) > 2 else EntityType.CONVEYOR,
                    self.layot_entity[4] if len(self.layot_entity) > 4 else Direction.NORTH,
                )
                self.conveyor_path = conv_path
                if conv_path:
                    conv_pos, conv_dir = conv_path[0]
                    if c.can_build_armoured_conveyor(conv_pos, conv_dir):
                        c.build_armoured_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end   = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    elif c.can_build_conveyor(conv_pos, conv_dir):
                        c.build_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end   = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    else:
                        self._try_mark_path_wip(c, conv_pos)
                    self.mode = 4
                    return
            end = target_end

        if c.is_in_vision(bridge_end):
            if not self._clear_tile(c, bridge_end):
                return

        building_id_be = c.get_tile_building_id(bridge_end)
        if (building_id_be is not None
                and c.get_entity_type(building_id_be) == EntityType.BARRIER
                and c.get_team(building_id_be) == c.get_team()):
            if c.can_destroy(bridge_end):
                c.destroy(bridge_end)
            return

        if c.can_build_bridge(bridge_end, end):
            c.build_bridge(bridge_end, end)
            self.last_path_built       = bridge_end
            self.last_bridge_end       = end
            self.last_bridge_built_pos = bridge_end
            self.bridge_destination    = None
            self.bridge_origin         = None
            if self.is_axionite_path:
                self.pending_axionite_marker = bridge_end
            if end in active_ends:
                self._full_reset()
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end))
                  in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR)
                  and c.get_team() == c.get_team(c.get_tile_building_id(end))):
                self.mode = 3
            else:
                self.mode = 2
        else:
            if self._try_mark_path_wip(c, bridge_end):
                if c.is_in_vision(bridge_end):
                    mark = c.get_tile_building_id(bridge_end)
                    val  = c.get_marker_value(mark)
                    if c.get_id() != _get_wip_marker_id(val):
                        self._full_reset()

    # ──────────────────────────────────────────────────────────────────────────
    # MODO 3: Revisar camino hacia la base
    # ──────────────────────────────────────────────────────────────────────────

    def revisar_camino_casa(self, c: Controller):
        current = c.get_position()

        if self.check_pos is None:
            self.check_pos = self.last_bridge_end

        if self.check_pos is None:
            self._full_reset()
            return

        if self.check_pos in self.end_bridges_titanium:
            self.check_pos = None
            self._full_reset()
            return

        c.draw_indicator_dot(self.check_pos, 255, 128, 0)

        if not c.is_in_vision(self.check_pos):
            d        = self.navegador.moveTo(c, self.check_pos, four_dirs=False)
            next_pos = current.add(d)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, d)

        if not c.is_in_vision(self.check_pos):
            return

        building_id = c.get_tile_building_id(self.check_pos)

        if building_id is None:
            self.last_bridge_end = self.check_pos
            self.check_pos       = None
            self.mode            = 2
            return

        entity = c.get_entity_type(building_id)

        if c.get_team(building_id) != c.get_team():
            self.last_bridge_end = self.check_pos
            self.check_pos       = None
            self.mode            = 2
            return

        if (
            (entity == EntityType.MARKER and _is_wip_marker(c.get_marker_value(building_id)))
            or entity == EntityType.BARRIER
            or entity in (EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER)
        ):
            self.check_pos = None
            self._full_reset()
            return

        if entity not in TRANSPORT_TYPES:
            self.last_bridge_end = self.check_pos
            self.check_pos       = None
            self.mode            = 2
            return

        next_check = None
        if entity == EntityType.BRIDGE:
            next_check = c.get_bridge_target(building_id)
        elif entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            next_check = self.check_pos.add(c.get_direction(building_id))
        else:
            d = c.get_direction(building_id)
            possible_dirs           = [d, d.rotate_left().rotate_left(), d.rotate_right().rotate_right()]
            out_of_vision_fallback  = None
            for dir_ in possible_dirs:
                ck_pos = self.check_pos.add(dir_)
                if not self._in_bounds(ck_pos):
                    continue
                if not c.is_in_vision(ck_pos):
                    out_of_vision_fallback = ck_pos
                    continue
                if c.get_tile_env(ck_pos) == Environment.WALL:
                    continue
                bid_  = c.get_tile_building_id(ck_pos)
                if bid_ is None:
                    continue
                etype_ = c.get_entity_type(bid_)
                if etype_ in TRANSPORT_TYPES and c.get_team() == c.get_team(bid_):
                    if etype_ in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR):
                        b_dir_ = c.get_direction(bid_)
                        if b_dir_ == ck_pos.direction_to(self.check_pos):
                            continue
                    elif etype_ == EntityType.SPLITTER:
                        b_dir_ = c.get_direction(bid_)
                        if b_dir_.opposite() == ck_pos.direction_to(self.check_pos):
                            continue
                    elif etype_ == EntityType.BRIDGE:
                        targ_ = c.get_bridge_target(bid_)
                        if targ_ == self.check_pos:
                            continue
                    next_check = ck_pos
                    break
                elif c.is_tile_passable(ck_pos):
                    next_check = ck_pos
            if next_check is None:
                next_check = out_of_vision_fallback

        if next_check is None:
            self.last_bridge_end = self.check_pos
            self.check_pos       = None
            self.mode            = 2
            return

        self.check_pos = next_check

    # ──────────────────────────────────────────────────────────────────────────
    # MODO 4: Colocar conveyors
    # ──────────────────────────────────────────────────────────────────────────

    def place_conveyors(self, c: Controller):
        if not self.conveyor_path:
            self._check_conveyor_chain_end(c, self.last_bridge_end)
            return

        current           = c.get_position()
        conv_pos, conv_dir = self.conveyor_path[0]

        if c.is_in_vision(conv_pos) and not self.is_axionite_path:
            next_bid = c.get_tile_building_id(conv_pos)
            if (next_bid is not None
                    and c.get_entity_type(next_bid) in (
                        EntityType.GUNNER, EntityType.SENTINEL,
                        EntityType.BREACH, EntityType.LAUNCHER)
                    and c.get_team(next_bid) != c.get_team()):
                threat = self._find_enemy_threat(c)
                if threat is not None:
                    self.conveyor_path.insert(0, (self.last_conveyor_pos, self.last_conveyor_dir))
                    self.last_bridge_end = (
                        self.last_conveyor_pos
                        if self.last_conveyor_pos is not None
                        else self.last_path_built
                    )
                    self._mode5_prev_mode    = self.mode
                    self._mode5_threat_pos   = conv_pos
                    self._mode5_absent_turns = 0
                    self._mode5_gone_since   = 0
                    self._mode5_sentinel_pos = None
                    self.mode = 5
                    self.defend_sentinel(c)
                    return

        if c.is_in_vision(conv_pos):
            next_bid = c.get_tile_building_id(conv_pos)
            if (next_bid is not None
                    and c.get_team() == c.get_team(next_bid)
                    and c.get_entity_type(next_bid) in TRANSPORT_TYPES):
                self.mode = 3
                return

        c.draw_indicator_dot(conv_pos, 26, 42, 219)
        c.draw_indicator_line(current, conv_pos, 26, 42, 219)

        if current.distance_squared(conv_pos) > 2:
            d        = self.navegador.moveTo(c, conv_pos, four_dirs=False)
            next_pos = current.add(d)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, d)
            return

        if c.is_in_vision(conv_pos):
            build_id = c.get_tile_building_id(conv_pos)
            if build_id is not None:
                entity = c.get_entity_type(build_id)
                team   = c.get_team(build_id)

                if (entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
                        and team == c.get_team()
                        and c.get_direction(build_id) == conv_dir):
                    self.last_conveyor_dir = conv_dir
                    self.conveyor_path.pop(0)
                    end = conv_pos.add(conv_dir)
                    self._check_conveyor_chain_end(c, end)
                    return

                if (team == c.get_team()
                        and entity in (EntityType.BRIDGE, EntityType.CONVEYOR,
                                       EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER)):
                    if (entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
                            and team == c.get_team()
                            and c.get_direction(build_id) == conv_dir) or \
                       entity not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                        self.conveyor_path.pop(0)
                        if entity == EntityType.BRIDGE:
                            end = c.get_bridge_target(build_id)
                        else:
                            end = conv_pos.add(c.get_direction(build_id))
                        if end is not None:
                            self.last_bridge_end = end
                            self._check_conveyor_chain_end(c, end)
                        return

                if not self._clear_tile(c, conv_pos):
                    return

        built = False
        if c.can_build_armoured_conveyor(conv_pos, conv_dir):
            c.build_armoured_conveyor(conv_pos, conv_dir)
            built = True
        elif c.can_build_conveyor(conv_pos, conv_dir):
            c.build_conveyor(conv_pos, conv_dir)
            built = True

        if built:
            self.last_path_built   = conv_pos
            self.last_conveyor_pos = conv_pos
            self.last_conveyor_dir = conv_dir
            self.conveyor_path.pop(0)
            end                  = conv_pos.add(conv_dir)
            self.last_bridge_end = end
            self._check_conveyor_chain_end(c, end)
        else:
            if self._try_mark_path_wip(c, conv_pos):
                if c.is_in_vision(conv_pos):
                    mark = c.get_tile_building_id(conv_pos)
                    val  = c.get_marker_value(mark)
                    if c.get_id() != _get_wip_marker_id(val):
                        self._full_reset()

    def _check_conveyor_chain_end(self, c: Controller, end: Position):
        if end in self._active_ends:
            self.conveyor_path     = []
            self.last_conveyor_dir = None
            self._full_reset()
            return

        # ── MODIFICACIÓN: sentinel si en rango ───────────────────────────────
        if end is not None and self._in_sentinel_range_of_enemy_core(end):
            self.conveyor_path     = []
            self.last_conveyor_dir = None
            placed = self._try_place_attack_sentinel(c, end)
            if placed:
                self._full_reset()
            return

        if not self.conveyor_path:
            self.last_conveyor_dir = None
            if end is not None and c.is_in_vision(end):
                end_bid = c.get_tile_building_id(end)
                if (end_bid is not None
                        and c.get_team(end_bid) == c.get_team()
                        and c.get_entity_type(end_bid) in (
                            EntityType.BRIDGE, EntityType.CONVEYOR,
                            EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER)):
                    self.mode = 3
                    return
            self.mode = 2

    # ──────────────────────────────────────────────────────────────────────────
    # MODO 5: Defender ruta con sentinel
    # ──────────────────────────────────────────────────────────────────────────

    _SENTINEL_ABSENT_THRESHOLD = 5

    def defend_sentinel(self, c: Controller):
        current      = c.get_position()
        sentinel_pos = self.last_bridge_end

        new_threat = self._find_enemy_threat(c)
        if new_threat is not None:
            self._mode5_threat_pos   = new_threat
            self._mode5_absent_turns = 0
            self._mode5_gone_since   = 0
        else:
            self._mode5_absent_turns += 1

        if self._mode5_absent_turns >= self._SENTINEL_ABSENT_THRESHOLD:
            if self._mode5_sentinel_pos is not None:
                sp = self._mode5_sentinel_pos
                if c.is_in_vision(sp):
                    bid = c.get_tile_building_id(sp)
                    if (bid is not None
                            and c.get_entity_type(bid) == EntityType.SENTINEL
                            and c.get_team(bid) == c.get_team()):
                        if current.distance_squared(sp) <= 2:
                            if c.can_destroy(sp):
                                c.destroy(sp)
                                self._mode5_sentinel_pos = None
                        else:
                            dir_ = self.navegador.moveTo(c, sp, four_dirs=False)
                            self._try_move(c, dir_)
                            return
                    else:
                        self._mode5_sentinel_pos = None
            if self._mode5_sentinel_pos is None:
                self.mode                = self._mode5_prev_mode
                self._mode5_threat_pos   = None
                self._mode5_absent_turns = 0
            return

        if self._mode5_sentinel_pos is not None:
            sp = self._mode5_sentinel_pos
            if c.is_in_vision(sp):
                bid = c.get_tile_building_id(sp)
                if (bid is None
                        or c.get_entity_type(bid) != EntityType.SENTINEL
                        or c.get_team(bid) != c.get_team()):
                    self._mode5_sentinel_pos = None
                elif self._mode5_threat_pos is not None:
                    sentinel_facing = c.get_direction(bid)
                    can_hit = c.can_fire_from(
                        sp, sentinel_facing, EntityType.SENTINEL, self._mode5_threat_pos
                    )
                    if not can_hit:
                        if current.distance_squared(sp) > 2:
                            dir_ = self.navegador.moveTo(c, sp, four_dirs=False)
                            self._try_move(c, dir_)
                            return
                        if c.can_destroy(sp):
                            c.destroy(sp)
                            self._mode5_sentinel_pos = None
                        return
            if self._mode5_threat_pos is not None:
                c.draw_indicator_line(current, self._mode5_threat_pos, 255, 20, 147)
            if self._mode5_sentinel_pos is not None:
                return

        if sentinel_pos is None or self._mode5_threat_pos is None:
            return

        c.draw_indicator_dot(sentinel_pos, 133, 8, 119)

        forbidden_dir: "Direction | None" = None
        for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
            neighbor = sentinel_pos.add(d.opposite())
            if not self._in_bounds(neighbor):
                continue
            if not c.is_in_vision(neighbor):
                continue
            nbid = c.get_tile_building_id(neighbor)
            if nbid is None:
                continue
            et = c.get_entity_type(nbid)
            if (et in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
                    and c.get_team(nbid) == c.get_team()
                    and c.get_direction(nbid) == d):
                forbidden_dir = d.opposite()
                break

        turret_dirs = [
            Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
            Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST,
        ]
        best_dir: "Direction | None" = None
        for d in turret_dirs:
            if d == forbidden_dir:
                continue
            if c.can_fire_from(sentinel_pos, d, EntityType.SENTINEL, self._mode5_threat_pos):
                best_dir = d
                break

        if best_dir is None:
            return

        if current.distance_squared(sentinel_pos) > 2:
            dir_ = self.navegador.moveTo(c, sentinel_pos, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)
            return

        bid = c.get_tile_building_id(sentinel_pos)

        our_barrier_there = (
            bid is not None
            and c.get_entity_type(bid) == EntityType.BARRIER
            and c.get_team(bid) == c.get_team()
            and self._mode5_barrier_pos == sentinel_pos
        )

        if our_barrier_there and c.get_global_resources()[0] >= c.get_sentinel_cost()[0]:
            if not self._clear_tile(c, sentinel_pos):
                return
            if current == sentinel_pos:
                dir_ = self.navegador._any_free_dir(c, False, self.map_w, self.map_h)
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir_)
            if c.can_build_sentinel(sentinel_pos, best_dir):
                self._mode5_barrier_pos = None
                c.build_sentinel(sentinel_pos, best_dir)
                self._mode5_sentinel_pos = sentinel_pos
            return

        if bid is not None:
            et = c.get_entity_type(bid)
            if et == EntityType.SENTINEL and c.get_team(bid) == c.get_team():
                self._mode5_sentinel_pos = sentinel_pos
                return
            if our_barrier_there:
                return

        if c.get_global_resources()[0] < c.get_barrier_cost()[0] or not self._clear_tile(c, sentinel_pos):
            return

        if current == sentinel_pos:
            dir_ = self.navegador._any_free_dir(c, False, self.map_w, self.map_h)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)

        if c.can_build_barrier(sentinel_pos):
            c.build_barrier(sentinel_pos)
            self._mode5_barrier_pos = sentinel_pos
        return

    # ──────────────────────────────────────────────────────────────────────────
    # MODO 6: Reparar cadena rota
    # ──────────────────────────────────────────────────────────────────────────

    def repair_broken_chain(self, c: Controller):
        current = c.get_position()

        if self._repair_broken_pos is None:
            self.mode = 0
            return

        chain_pos = self._repair_chain_pos
        if chain_pos is None:
            chain_pos = self._repair_broken_pos

        c.draw_indicator_dot(chain_pos, 0, 200, 255)
        c.draw_indicator_line(current, chain_pos, 0, 200, 255)

        if not c.is_in_vision(chain_pos):
            dir_  = self.navegador.moveTo(c, chain_pos, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)
            return

        bid = c.get_tile_building_id(chain_pos)

        if bid is None or c.get_team(bid) != c.get_team():
            self._commit_repair(c)
            return

        et = c.get_entity_type(bid)

        if et == EntityType.HARVESTER:
            self._repair_harvester  = chain_pos
            ore_env = c.get_tile_env(chain_pos)
            self.is_axionite_path   = (ore_env == Environment.ORE_AXIONITE)
            self.current_target     = chain_pos
            self.last_bridge_end    = self._repair_broken_pos
            self.last_path_built    = self._repair_broken_pos
            self._repair_broken_pos = None
            self._repair_chain_pos  = None
            self._repair_harvester  = None
            self.mode = 2
            return

        if et not in TRANSPORT_TYPES:
            self._commit_repair(c)
            return

        upstream_found: Position | None = None
        for ddx in range(-3, 4):
            for ddy in range(-3, 4):
                dsq = ddx * ddx + ddy * ddy
                if dsq == 0 or dsq > 9:
                    continue
                nb = Position(chain_pos.x + ddx, chain_pos.y + ddy)
                if not self._in_bounds(nb):
                    continue
                if not c.is_in_vision(nb):
                    continue
                nb_bid = c.get_tile_building_id(nb)
                if nb_bid is None:
                    continue
                if c.get_team(nb_bid) != c.get_team():
                    continue
                nb_et = c.get_entity_type(nb_bid)
                if nb_et == EntityType.HARVESTER:
                    upstream_found = nb
                    break
                if nb_et not in TRANSPORT_TYPES:
                    continue
                nb_out = self._transport_output_pos(c, nb_bid, nb)
                if nb_out == chain_pos:
                    upstream_found = nb
                    break
            else:
                continue
            break

        if upstream_found is not None:
            self._repair_chain_pos = upstream_found
            if c.is_in_vision(upstream_found):
                self.repair_broken_chain(c)
            else:
                dir_  = self.navegador.moveTo(c, upstream_found, four_dirs=False)
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir_)
        else:
            if current.distance_squared(chain_pos) <= 2:
                self._commit_repair(c)
            else:
                dir_  = self.navegador.moveTo(c, chain_pos, four_dirs=False)
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir_)

    def _commit_repair(self, c: Controller):
        if self._repair_broken_pos is not None:
            self.last_bridge_end = self._repair_broken_pos
            self.last_path_built = self._repair_broken_pos
        self._repair_broken_pos = None
        self._repair_chain_pos  = None
        self._repair_harvester  = None
        self.mode = 2

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers de cadenas / limpieza (idénticos a builder.py)
    # ──────────────────────────────────────────────────────────────────────────

    def _transport_output_pos(self, c: Controller, bid: int, pos: Position) -> "Position | None":
        et = c.get_entity_type(bid)
        try:
            if et == EntityType.BRIDGE:
                return c.get_bridge_target(bid)
            elif et in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                return pos.add(c.get_direction(bid))
        except Exception:
            pass
        return None

    def _try_mark_path_wip(self, c: Controller, pos: Position) -> bool:
        if not self._in_bounds(pos):
            return False
        return _place_wip_marker(c, pos)

    def _chain_output_is_broken(self, c: Controller, bid: int, pos: Position) -> bool:
        output = self._transport_output_pos(c, bid, pos)
        if output is None:
            return False
        if not self._in_bounds(output):
            return False
        if output in self._active_ends or output in self.layout_pos:
            return False
        if not c.is_in_vision(output):
            return False

        out_bid = c.get_tile_building_id(output)
        if out_bid is None:
            return True
        out_et   = c.get_entity_type(out_bid)
        out_team = c.get_team(out_bid)

        if out_team != c.get_team():
            return True
        if _is_wip_placeholder(c, out_bid):
            return False
        if out_et == EntityType.BARRIER:
            return False
        if out_et in (EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER):
            return False
        if out_et not in TRANSPORT_TYPES:
            return True
        return False

    def _scan_broken_chains(self, c: Controller) -> "tuple[Position, Position] | None":
        for b in c.get_nearby_buildings():
            if c.get_team(b) != c.get_team():
                continue
            et = c.get_entity_type(b)
            if et not in TRANSPORT_TYPES:
                continue
            bpos = c.get_position(b)
            if bpos in self.layout_pos:
                continue
            if not self._chain_output_is_broken(c, b, bpos):
                continue

            upstream = bpos
            for ddx in range(-3, 4):
                for ddy in range(-3, 4):
                    dsq = ddx * ddx + ddy * ddy
                    if dsq == 0 or dsq > 9:
                        continue
                    nb = Position(bpos.x + ddx, bpos.y + ddy)
                    if not self._in_bounds(nb):
                        continue
                    if not c.is_in_vision(nb):
                        continue
                    nb_bid = c.get_tile_building_id(nb)
                    if nb_bid is None:
                        continue
                    if c.get_team(nb_bid) != c.get_team():
                        continue
                    nb_et  = c.get_entity_type(nb_bid)
                    if nb_et not in TRANSPORT_TYPES:
                        continue
                    nb_out = self._transport_output_pos(c, nb_bid, nb)
                    if nb_out == bpos:
                        upstream = nb
                        break
                else:
                    continue
                break

            return (bpos, upstream)
        return None

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        building_id = c.get_tile_building_id(target)
        if building_id is None:
            return True

        current  = c.get_position()
        is_ally  = c.get_team(building_id) == c.get_team()

        if is_ally:
            if c.can_destroy(target):
                c.destroy(target)
                return True
            dir_ = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)
            return False
        else:
            if current == target:
                if c.can_fire(target):
                    c.fire(target)
                    return c.get_tile_building_id(target) is None
                return False
            else:
                if c.is_tile_passable(target):
                    dir_ = self.navegador.moveTo(c, target, four_dirs=False)
                    next_pos = current.add(dir_)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    self._try_move(c, dir_)
                return False

    def place_axionite_marker(self, c: Controller):
        current = c.get_position()
        if self.pending_axionite_marker is None:
            return
        bridge_pos = self.pending_axionite_marker

        best_empty: tuple | None = None
        best_road:  tuple | None = None
        best_pass:  tuple | None = None

        for ddx in range(-1, 2):
            for ddy in range(-1, 2):
                if ddx == 0 and ddy == 0:
                    continue
                cand = Position(bridge_pos.x + ddx, bridge_pos.y + ddy)
                if not self._in_bounds(cand):
                    continue
                if not c.is_in_vision(cand):
                    continue
                if c.get_tile_env(cand) != Environment.EMPTY:
                    continue
                if cand in self.layout_pos:
                    continue
                dist_bot = current.distance_squared(cand)
                bid_     = c.get_tile_building_id(cand)
                if bid_ is None:
                    if best_empty is None or dist_bot < best_empty[0]:
                        best_empty = (dist_bot, cand)
                else:
                    et_ = c.get_entity_type(bid_)
                    tm_ = c.get_team(bid_)
                    if tm_ == c.get_team() and et_ == EntityType.ROAD:
                        if best_road is None or dist_bot < best_road[0]:
                            best_road = (dist_bot, cand)
                    elif c.is_tile_passable(cand) and tm_ != c.get_team():
                        if best_pass is None or dist_bot < best_pass[0]:
                            best_pass = (dist_bot, cand)

        chosen      = best_empty or best_road or best_pass
        marker_spot = chosen[1] if chosen is not None else None

        if marker_spot is None:
            return

        if current.distance_squared(marker_spot) > 2:
            d = self.navegador.moveTo(c, marker_spot, four_dirs=False)
            self._try_move(c, d)
            return

        if c.get_tile_building_id(marker_spot) is not None:
            if not self._clear_tile(c, marker_spot):
                return

        marker_val = _encode_axionite_marker(bridge_pos)
        if c.can_place_marker(marker_spot):
            c.place_marker(marker_spot, marker_val)
            self.pending_axionite_marker = None

    # ──────────────────────────────────────────────────────────────────────────
    # Scoring para _find_best_bridge_end
    # ──────────────────────────────────────────────────────────────────────────

    _MERGE_TIEBREAK = 2
    _CARGO_PENALTY  = -200

    def _chain_has_axionite(self, c: Controller, start_pos: Position, depth: int = 2) -> bool:
        pos     = start_pos
        visited = {pos}
        for _ in range(depth):
            if not c.is_in_vision(pos):
                break
            bid = c.get_tile_building_id(pos)
            if bid is None:
                break
            et   = c.get_entity_type(bid)
            team = c.get_team(bid)
            if team != c.get_team():
                break
            if et != EntityType.BRIDGE:
                if pos in self.end_bridges_axionite:
                    return self.is_axionite_path
                break
            if _bridge_is_axionite_tagged(c, pos):
                return True
            try:
                stored = c.get_stored_resource(bid)
                if stored in (ResourceType.RAW_AXIONITE, ResourceType.REFINED_AXIONITE):
                    return True
            except Exception:
                pass
            nxt = None
            try:
                nxt = c.get_bridge_target(bid)
            except Exception:
                pass
            if nxt is None or nxt in visited:
                break
            visited.add(nxt)
            pos = nxt
        return False

    def _loops_to_me(self, c: Controller, id: int, depth: int = 6):
        me = self.last_bridge_end
        for _ in range(depth):
            entity = c.get_entity_type(id)
            end    = None
            if entity == EntityType.BRIDGE:
                end = c.get_bridge_target(id)
            elif entity in TRANSPORT_TYPES:
                end = c.get_position(id).add(c.get_direction(id))
            else:
                return False
            if end == me:
                return True
            elif c.is_in_vision(end) and self._in_bounds(end):
                id = c.get_tile_building_id(end)
                if c.get_entity_type(id) not in TRANSPORT_TYPES:
                    return False
            else:
                return False

    def _transport_congestion_penalty(self, bid, pos, get_cached) -> int:
        penalty = 0
        entry   = get_cached(pos)
        if entry is None:
            return 0
        _, entity, team, stored, pos_output = entry
        if stored is not None:
            penalty += self._CARGO_PENALTY

        total_connected  = 0
        loaded_connected = 0
        for ddx in range(-3, 4):
            for ddy in range(-3, 4):
                if ddx == 0 and ddy == 0:
                    continue
                nb       = Position(pos.x + ddx, pos.y + ddy)
                nb_entry = get_cached(nb)
                if nb_entry is None:
                    continue
                _, nb_entity, nb_team, nb_stored, nb_output = nb_entry
                if nb_team != team:
                    continue
                if nb_entity not in TRANSPORT_TYPES:
                    continue
                connected = False
                if nb_output == pos:
                    connected = True
                elif pos_output is not None and pos_output == nb:
                    connected = True
                if not connected:
                    continue
                total_connected += 1
                if nb_stored is not None:
                    loaded_connected += 1

        if total_connected > 0:
            penalty += int(self._CARGO_PENALTY * loaded_connected / total_connected)
        return penalty

    def _resolve_chain_endpoint(self, start_pos, start_bid, start_entity, get_cached):
        pos     = start_pos
        entity  = start_entity
        bid     = start_bid
        visited = {pos}
        for _ in range(20):
            if entity == EntityType.BRIDGE:
                entry = get_cached(pos)
                nxt   = entry[4] if entry else None
            elif entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                entry = get_cached(pos)
                nxt   = entry[4] if entry else None
            else:
                break
            if nxt is None or nxt in visited:
                break
            if nxt in self._active_ends:
                return nxt
            nxt_entry = get_cached(nxt)
            if nxt_entry is None:
                break
            nxt_bid, nxt_et, nxt_team, _, _ = nxt_entry
            if nxt_team != get_cached(pos)[2]:
                break
            if nxt_et not in TRANSPORT_TYPES:
                break
            visited.add(nxt)
            pos    = nxt
            entity = nxt_et
            bid    = nxt_bid
        return pos

    def _find_best_bridge_end(self, place, c, builds) -> "Position | None":
        import math as _math

        building_cache: dict = {}

        def get_cached(pos):
            if pos in building_cache:
                return building_cache[pos]
            if not c.is_in_vision(pos):
                building_cache[pos] = None
                return None
            if not _is_in_bounds(c, pos):
                building_cache[pos] = None
                return None
            bid_  = c.get_tile_building_id(pos)
            if bid_ is None:
                building_cache[pos] = None
                return None
            et_     = c.get_entity_type(bid_)
            team_   = c.get_team(bid_)
            stored_ = None
            try:
                stored_ = c.get_stored_resource(bid_)
            except Exception:
                pass
            output_ = None
            if et_ == EntityType.BRIDGE:
                try:
                    output_ = c.get_bridge_target(bid_)
                except Exception:
                    pass
            elif et_ in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                try:
                    output_ = pos.add(c.get_direction(bid_))
                except Exception:
                    pass
            building_cache[pos] = (bid_, et_, team_, stored_, output_)
            return building_cache[pos]

        sorted_ends  = sorted(self._active_ends, key=lambda p: place.distance_squared(p))
        final_target = None
        for e in sorted_ends:
            if e != self.last_bridge_end and self._in_bounds(e):
                final_target = e
                break

        if final_target is None:
            return None

        dx = final_target.x - place.x
        dy = final_target.y - place.y
        dist_to_final = _math.sqrt(dx * dx + dy * dy)
        if dist_to_final == 0:
            return None
        ux, uy = dx / dist_to_final, dy / dist_to_final

        best_pos:   "Position | None" = None
        best_score: "float | None"    = None

        for ddx in range(-3, 4):
            for ddy in range(-3, 4):
                d_sq = ddx * ddx + ddy * ddy
                if d_sq == 0 or d_sq > 9:
                    continue

                candidate = Position(place.x + ddx, place.y + ddy)
                if candidate == self.last_bridge_end:
                    continue
                if not self._in_bounds(candidate):
                    continue
                if not c.is_in_vision(candidate):
                    continue
                if candidate not in self._active_ends and candidate in self.layout_pos:
                    continue

                env = c.get_tile_env(candidate)
                if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE, Environment.WALL):
                    continue

                merge_bonus    = 0
                congestion_pen = 0

                _cache_entry = get_cached(candidate)
                bid_c    = _cache_entry[0] if _cache_entry else None
                entity_c = _cache_entry[1] if _cache_entry else None
                team_c   = _cache_entry[2] if _cache_entry else None

                effective_end = candidate

                if bid_c is not None:
                    if team_c == c.get_team():
                        if entity_c in TRANSPORT_TYPES:
                            if entity_c == EntityType.BRIDGE:
                                chain_is_axionite = (
                                    _bridge_is_axionite_tagged(c, candidate)
                                    or self._chain_has_axionite(c, candidate)
                                )
                                if self.is_axionite_path and not chain_is_axionite and \
                                   candidate not in self.end_bridges_axionite:
                                    continue
                                if self.is_axionite_path and self._loops_to_me(c, bid_c) and \
                                   candidate not in self.end_bridges_axionite:
                                    continue
                                if not self.is_axionite_path and chain_is_axionite:
                                    continue
                            elif self.is_axionite_path and candidate not in self.end_bridges_axionite:
                                continue
                            merge_bonus = 100 if self.is_axionite_path else self._MERGE_TIEBREAK
                            effective_end = self._resolve_chain_endpoint(
                                candidate, bid_c, entity_c, get_cached
                            )
                            congestion_pen = 0
                            if not self.is_axionite_path:
                                congestion_pen = self._transport_congestion_penalty(
                                    bid_c, candidate, get_cached
                                )
                        elif entity_c == EntityType.CORE:
                            continue
                        elif (not c.is_tile_passable(candidate)
                              and c.get_tile_builder_bot_id(candidate) is None):
                            continue
                    else:
                        if not c.is_tile_passable(candidate):
                            continue

                plus = 0
                if self.is_axionite_path and candidate in self.end_bridges_axionite:
                    plus = 200

                remaining_sq = effective_end.distance_squared(final_target)
                dot          = ddx * ux + ddy * uy
                score        = -remaining_sq + dot + merge_bonus + congestion_pen + plus

                if best_score is None or score > best_score:
                    best_score = score
                    best_pos   = candidate

        return best_pos
    

    # ──────────────────────────────────────────────────────────────────────────
    # ENTRADA PRINCIPAL
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, c: Controller):
        self._connected_cache = {}
        current = c.get_position()

        if c.can_heal(current):
            c.heal(current)

        # Inicialización tardía del core aliado
        if self.spawn is None:
            for b in c.get_nearby_buildings():
                if (c.get_entity_type(b) == EntityType.CORE
                        and c.get_team(b) == c.get_team()):
                    self.spawn = c.get_position(b)
                    self._init_enemy_candidates()
                    layout = compute_layout_for_core(c, self.spawn)
                    self.layout_pos   = layout['layout_positions']
                    self.layot_entity = layout['layout']
                    break

        # ── FASE A: Buscar y confirmar el core enemigo ────────────────────────
        if self.enemy_core_pos is None:
            c.draw_indicator_dot(current, 255, 255, 0)
            self._find_enemy_core(c)
            return

        if not self.has_seen_enemy_core:
            c.draw_indicator_dot(current, 255, 200, 0)
            self._go_to_enemy_core(c)
            return

        # Calcular endpoints enemigos si aún no los tenemos
        if not self.end_bridges_titanium:
            self._init_enemy_endpoints(c)
            if not self.end_bridges_titanium:
                # No tenemos endpoints válidos aún; movernos hacia el core enemigo
                self._navigate_to(c, self.enemy_core_pos)
                return

        # ── FASE B: Construir cadenas hacia el core enemigo ───────────────────
        self.place_axionite_marker(c)

        if self.mode == 0:
            c.draw_indicator_dot(current, 255, 255, 255)
            self.buscar_material(c, current)
        elif self.mode == 1:
            c.draw_indicator_dot(current, 24, 184, 69)
            self.place_bridge_ore(c)
        elif self.mode == 2:
            c.draw_indicator_dot(current, 204, 16, 73)
            self.bridgeHome(c)
            if self.mode == 2 and self.last_bridge_end is not None and not self.is_axionite_path:
                threat = self._find_enemy_threat(c)
                if threat is not None:
                    self._mode5_prev_mode    = self.mode
                    self._mode5_threat_pos   = threat
                    self._mode5_absent_turns = 0
                    self._mode5_gone_since   = 0
                    self._mode5_sentinel_pos = None
                    self.mode = 5
        elif self.mode == 3:
            c.draw_indicator_dot(current, 237, 129, 26)
            self.revisar_camino_casa(c)
        elif self.mode == 4:
            c.draw_indicator_dot(current, 26, 42, 219)
            self.place_conveyors(c)
            if self.mode == 4 and self.last_bridge_end is not None and not self.is_axionite_path:
                threat = self._find_enemy_threat(c)
                if threat is not None:
                    self._mode5_prev_mode    = self.mode
                    self._mode5_threat_pos   = threat
                    self._mode5_absent_turns = 0
                    self._mode5_gone_since   = 0
                    self._mode5_sentinel_pos = None
                    self.mode = 5
        elif self.mode == 5:
            c.draw_indicator_dot(current, 255, 20, 147)
            self.defend_sentinel(c)
        elif self.mode == 6:
            c.draw_indicator_dot(current, 0, 200, 255)
            self.repair_broken_chain(c)