from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position, ResourceType
import math
import bignav_a_mem as bugnav

from botRolex.helper.layout_defensivo import compute_layout_for_core

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    # Kept for backward compatibility; use self._in_bounds() inside the class.
    w = c.get_map_width()
    h = c.get_map_height()
    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

def revisor_casillas_extractor(c: Controller, pos: Position):
    # lógica para revisar casillas alrededor del extractor
    Existe = False
    casillas = [pos.add(Direction.NORTH), pos.add(Direction.EAST), pos.add(Direction.SOUTH), pos.add(Direction.WEST)]

    for casilla in casillas:
        if _is_in_bounds(c, casilla):
            if c.is_in_vision(casilla):
                building_id = c.get_tile_building_id(casilla)
                if building_id is not None and c.get_entity_type(building_id) in TRANSPORT_TYPES and c.get_team(building_id) == c.get_team():
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

# ── Axionite bridge marker encoding ─────────────────────────────────────────
# Format: 833_xx_yy  →  integer = 833 * 10000 + x * 100 + y
# Works for map coordinates 0–99 in each axis.
_AXIONITE_MARKER_IDENT = 833

# ── WIP bridge marker encoding ─────────────────────────────────────────
# WIP: Work In Progress
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
    """True si hay un marker aliado de axionita en bridge_pos o adyacente cardinal."""
    for check in [bridge_pos.add(Direction.NORTH),
                  bridge_pos.add(Direction.EAST),
                  bridge_pos.add(Direction.SOUTH),
                  bridge_pos.add(Direction.WEST),
                  bridge_pos.add(Direction.NORTHEAST),
                  bridge_pos.add(Direction.NORTHWEST),
                  bridge_pos.add(Direction.SOUTHEAST),
                  bridge_pos.add(Direction.SOUTHWEST)]:
        if not _is_in_bounds(c, check):
            continue
        if not c.is_in_vision(check):
            continue
        mid = c.get_tile_building_id(check)
        if mid is not None and c.get_entity_type(mid) == EntityType.MARKER and c.get_team(mid) == c.get_team():
            val = c.get_marker_value(mid)
            if _is_axionite_marker(val) and _decode_axionite_marker_pos(val) == bridge_pos:
                return True
    return False

def _is_conv_better(c: Controller, ini: Position, end: Position, layout, entity_end: EntityType, direction_end: Direction):
    """
    BFS desde ini hasta end. En cada paso el coste acumulado es:
        (i + 0.01 * i) * conveyor_cost  donde i = número de pasos
    Si encontramos camino antes de superar bridge_cost, devuelve
    lista de (pos, dir) para colocar las conveyors. Si no, None.
    """
    conveyor_cost = c.get_conveyor_cost()[0]
    bridge_cost = c.get_bridge_cost()[0]

    from collections import deque
    queue = deque()
    queue.append((ini, []))
    visited = {ini}

    while queue:
        current, path = queue.popleft()

        # Cortar si ya es imposible que sea más barato
        i = len(path) + 1  # pasos que tendría el path al añadir este vecino
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
                if entity == EntityType.ROAD or (entity == EntityType.BARRIER and c.get_team() == c.get_team(building_id)):
                    pass  # tratar como casilla libre
                elif not (c.is_tile_passable(neighbor) and c.get_tile_builder_bot_id(neighbor) is None) and (entity != EntityType.BARRIER or c.get_team() != c.get_team(building_id)):
                    if neighbor != c.get_position() and entity not in TRANSPORT_TYPES:
                        continue
                elif entity in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR, EntityType.BRIDGE) and c.get_team() == c.get_team(building_id):
                    # Permitir si es el destino final, saltar si es nodo intermedio
                    if neighbor != end:
                        continue
                elif entity == EntityType.SPLITTER and c.get_team() == c.get_team(building_id):
                     # Permitir si es el destino final, saltar si es nodo intermedio
                    if neighbor != end or d != c.get_direction(building_id):
                        continue

            if neighbor == end and entity_end == EntityType.SPLITTER and d != direction_end:
                continue

            new_path = path + [(current, d)]
        
            if neighbor == end:
                return new_path  # longitud = i, ya verificada arriba
                
            visited.add(neighbor)
            queue.append((neighbor, new_path))

    return None  # no hay camino dentro del presupuesto


class Harvester:
    def __init__(self, c: Controller):
        self.objetivos = []
        self.objetivos_set = set()   # espejo de self.objetivos para lookups O(1)
        self.recolectores = []
        self.recolectores_set = set()  # espejo de self.recolectores para lookups O(1)

        # Dimensiones del mapa cacheadas — el mapa no cambia nunca
        self.map_w = c.get_map_width()
        self.map_h = c.get_map_height()

        # Builder Vars
        self.navegador = bugnav.BugNav()
        self.spawn = None
        self.current_target = None

        self.conveyor_path = []      # lista de (pos, dir) para mode 4
        self.mode_after_conv = 2     # modo al que volver al terminar mode 4

        self.mode = 0
            # mode 0: Find Ore (Blanco)
            # mode 1: Place bridge near Ore (Verde)
            # mode 2: go home (Rojo)
            # mode 3: revisar estructura (Naranja)
            # mode 4: conveyor mode (Azul Oscuro)
            # mode 5: defender ruta con sentinel (Rosa)
            # mode 6: rastrear cadena rota upstream hasta harvester (Cian)
            # mode 7: Barriers en Harvester (Verde no azul)
        self.last_bridge_end = None
        self.last_bridge_built_pos = None
        self.last_conveyor_pos: Position | None = None   # posición del último conveyor colocado en modo 4
        self.last_conveyor_dir: Direction | None = None     
        self.last_path_built: Position | None = None     # posición de la útima construcción del camino
        self.check_pos = None

        # Variables de puentes
        self.bridge_origin = None         # casilla origen del puente pendiente de construir
        self.bridge_destination = None    # casilla destino del puente pendiente de construir

        self.turret_places = []

        # Cache de IDs de puentes verificados como conectados a la base en este turno
        self._connected_cache: dict[int, bool] = {}

        # Tipo de camino activo: True = axionita (solo bridges + markers), False = titanio
        self.is_axionite_path: bool = False

        # Posición del bridge de axionita que espera ser marcado (None = ninguno pendiente).
        # El marker se coloca en una casilla adyacente (dist² ≤ 2) al bridge, así que
        # se intenta al inicio del siguiente turno desde run(), moviéndonos si hace falta.
        self.pending_axionite_marker: Position | None = None

        # Endpoints separados por tipo de recurso.
        # Se rellenan al final de __init__ una vez que end_bridges esté listo.
        self.end_bridges_axionite: list[Position] = []  # primero de end_bridges
        self.end_bridges_titanium: list[Position] = []  # el resto

        # Priority to build Titatium before Axionite
        self.titanium_harvesters: set[Position] = set()

        # Ban ore si no podemos llegar
        self.banned_ores: set[Position] = set()

        # ── Modo 5: defensa con sentinel ─────────────────────────────────────
        # mode 5: Defender ruta colocando un sentinel en last_bridge_end
        #   - Se activa desde modos 2/3/4 al ver un enemigo (bot o torreta)
        #   - Espera a que el objetivo lleve ≥5 turnos sin aparecer
        #   - Destruye el sentinel y retoma el modo anterior
        self._mode5_prev_mode: int = 2          # modo al que volver al salir
        self._mode5_threat_pos: Position | None = None   # última pos del enemigo
        self._mode5_sentinel_pos: Position | None = None # donde construimos el sentinel
        self._mode5_gone_since: int = 0         # turno en que el enemigo desapareció
        self._mode5_absent_turns: int = 0       # turnos consecutivos sin ver al enemigo
        self._mode5_barrier_pos: Position | None = None

        # ── Modo 6: reparar cadena rota ───────────────────────────────────────
        # Se activa desde modo 0 cuando se detecta un nodo de transporte aliado
        # cuyo output está desconectado (cadena rota sin harvester al final).
        #
        # _repair_broken_pos : posición del nodo roto — último elemento de la
        #                      cadena que sí existe. El modo 2 retomará la
        #                      construcción desde aquí.
        # _repair_chain_pos  : posición que rastreamos en cada tick, moviéndonos
        #                      upstream (hacia el harvester fuente) hasta verla.
        # _repair_harvester  : posición del harvester fuente, una vez encontrado.
        #                      Cuando se fija, pasamos a modo 2.
        self._repair_broken_pos: Position | None = None
        self._repair_chain_pos: Position | None = None
        self._repair_harvester: Position | None = None

        # ── Modo 7: defensa con Barrier a Harvester ─────────────────────────────────────
        self.mode_after_barrier: int = 0
        self.pending_barriers_harvester: set[Position] = set()

        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE and c.get_team() == c.get_team(b):
                self.spawn = c.get_position(b)
                break

        s = self.spawn
        layout = compute_layout_for_core(c, s)

        self.layout_pos = layout['layout_positions']
        self.end_bridges_axionite = layout['axionite_entry']
        self.end_bridges_titanium = layout['entry_positions']
        self.layot_entity = layout['layout']

    def _in_bounds(self, pos: Position) -> bool:
        """Versión cacheada de _is_in_bounds — sin llamadas a la API."""
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    def _make_pending_barriers(
        self,
        c: Controller,
        viable_places: list[Position],
        extra_places_for_turrent: list[Position],
        reserved_positions: list[Position] | None = None,
    ) -> set[Position]:
        pending = set(viable_places).union(extra_places_for_turrent)
        pending -= self.layout_pos

        if reserved_positions is not None:
            pending -= set(reserved_positions)

        filtered = set()
        for pos in pending:
            if not self._in_bounds(pos):
                continue
            if c.is_in_vision(pos):
                bid = c.get_tile_building_id(pos)
                if bid is not None and c.get_entity_type(bid) in TRANSPORT_TYPES and c.get_team() == c.get_team(bid):
                    continue
            filtered.add(pos)
        return filtered

    @property
    def _active_ends(self) -> list:
        """Devuelve la lista de endpoints correcta según el tipo de camino activo."""
        if self.is_axionite_path:
            return self.end_bridges_axionite
        return self.end_bridges_titanium if self.end_bridges_titanium else self.layout_pos

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        """
        Intenta mover el bot en `direction`.
        Devuelve True si el bot se movió efectivamente, False si no.
        """
        if direction == Direction.CENTRE:
            return False

        dest = c.get_position().add(direction)

        if not self._in_bounds(dest):
            return False

        if c.can_move(direction):
            c.move(direction)
            return True

        return False

    def run(self, c: Controller):
        # Limpiar cache de conectividad de puentes al inicio de cada turno
        self._connected_cache = {}
        current = c.get_position()

        if c.can_heal(current):
            c.heal(current)

        self.place_axionite_marker(c)

        # ── Detección de amenaza enemiga (desde modos 2, (3?) y 4) ─────────────
        

        if self.mode == 0:
            c.draw_indicator_dot(current, 255, 255, 255)
            self.buscar_material(c, current)
        if self.mode == 1:
            c.draw_indicator_dot(current, 24, 184, 69)
            self.place_bridge_ore(c)
        elif self.mode == 2:
            c.draw_indicator_dot(current, 204, 16, 73)
            self.bridgeHome(c)
            # Activamos modo 5 si vemos una torreta enemiga,
            # tenemos un last_bridge_end donde poder colocar el sentinel,
            # y aún no estamos en modo 5.
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
            # Activamos modo 5 si vemos una torreta enemiga,
            # tenemos un last_bridge_end donde poder colocar el sentinel,
            # y aún no estamos en modo 5.
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
            c.draw_indicator_dot(current, 0, 200, 255)   # Cian
            self.repair_broken_chain(c)
        elif self.mode == 7:
            c.draw_indicator_dot(current, 0, 255, 187)
            self.barrier_harvester(c)

    # helper de mode 0
    def _has_viable_adjacent(self, c: Controller, tile: Position) -> bool:
        """
        Devuelve True si el ore en `tile` tiene al menos una casilla cardinal
        adyacente donde sea posible construir un harvester (no wall, in-bounds,
        sin edificio bloqueante no-aliado).
        """
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
                # Passable (conveyor aliada, etc.) también vale
                if c.is_tile_passable(adj):
                    return True
            else:
                # Fuera de visión: asumir viable (no rechazar prematuramente)
                return True
        return False

    def oreCerca(self, c: Controller):
        lista = c.get_nearby_tiles()
        changed = False
        ronda = c.get_current_round()
        for tile in lista:
            if tile in self.banned_ores:
                continue

            env = c.get_tile_env(tile)  # llamada única por tile
            es_mineral = (env == Environment.ORE_TITANIUM or
                          (env == Environment.ORE_AXIONITE and c.get_global_resources()[1] < 533) and len(self.titanium_harvesters) > 1)
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
                    continue  # ore completamente bloqueado — ignorar

                building_id = c.get_tile_building_id(tile)

                if building_id is not None:
                    entity = c.get_entity_type(building_id)
                    team = c.get_team() == c.get_team(building_id)
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
                        if not ((c.is_tile_passable(tile) or c.get_position() == tile) or (entity == EntityType.BARRIER and team)):
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

    # MODE 0

    def buscar_material(self, c: Controller, current: Position):
        # ── PRIORIDAD 1: detectar cadenas de transporte aliadas rotas ─────────
        # Antes de buscar ore nuevo, comprobamos si alguna cadena ya construida
        # tiene el output desconectado (casilla vacía o con elemento no-transporte).
        # Si encontramos una, pasamos a modo 6 para rastrear upstream hasta el
        # harvester y retomar la construcción desde el nodo roto.
        broken = self._scan_broken_chains(c)
        if broken is not None:
            broken_pos, upstream_pos = broken
            self._repair_broken_pos = broken_pos
            self._repair_chain_pos  = upstream_pos
            self._repair_harvester  = None
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

        if len(self.objetivos) > 0 and self.current_target is None:
            target = self.objetivos[0]
        elif len(self.recolectores) > 0 and self.current_target is None:
            target = self.recolectores[0]
        else:
            target = None

        if target is not None:
            c.draw_indicator_line(current, target, 204, 39, 245)

            if c.is_in_vision(target):
                build_id = c.get_tile_building_id(target)
                if (build_id is not None and c.get_entity_type(build_id) != EntityType.HARVESTER 
                    and not self._clear_tile(c, target)):
                        return  # Aún no lo hemos roto

            if c.can_place_marker(target):
                c.place_marker(target, c.get_id())
                self.reserved = True
                self.current_target = target

            if c.can_build_harvester(target):
                c.build_harvester(target)
                self.current_target = target
                if target in self.objetivos_set:
                    self.objetivos.remove(target)
                    self.objetivos_set.discard(target)
                # Determinar si el ore es axionita para separar el camino de vuelta
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
                # Estamos al lado del target pero no podemos construir harvester
                b_id = c.get_tile_building_id(target)
                if b_id is not None and c.get_entity_type(b_id) == EntityType.HARVESTER and not revisor_casillas_extractor(c, c.get_position(b_id)):
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

    # MODE 1

    def place_bridge_ore(self, c: Controller):
        places = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
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
                c.draw_indicator_dot(c.get_position(), 237, 129, 26)
                self.revisar_camino_casa(c)
                return

        viable_places = []
        extra_places_for_turrent = []
        for d in places:
            spot = self.current_target.add(d)
            if self._in_bounds(spot) and c.is_in_vision(spot):
                something = c.get_tile_building_id(spot)
                something2 = c.get_tile_env(spot)

                if (something is None or c.is_tile_passable(spot) or spot == c.get_position() or c.get_entity_type(something) == EntityType.MARKER) and something2 != Environment.WALL:
                    if something is not None and c.get_team() == c.get_team(something):
                        etype = c.get_entity_type(something)
                        if etype == EntityType.MARKER:
                            if _get_wip_marker_id(c.get_marker_value(something)) == c.get_id():
                                viable_places.insert(0, spot)
                                break
                            else:
                                # id distinta
                                self.current_target = None
                                self.mode = 0
                                self.last_bridge_built_pos = None
                                self.last_conveyor_pos = None
                                self.last_path_built = None
                                return

                    if something2 not in [Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]:
                        viable_places.append(spot)
                    else:
                        extra_places_for_turrent.append(spot)
                elif something is not None and c.get_entity_type(something) == EntityType.BARRIER and c.get_team() == c.get_team(something):
                    viable_places.append(spot)
                    
        if len(viable_places) == 0:
            if len(extra_places_for_turrent) == 0:
                self.current_target = None
                self.mode = 0
                self.last_bridge_built_pos = None
                self.last_conveyor_pos = None
                self.last_path_built = None
                return
            viable_places = extra_places_for_turrent

        current = c.get_position()
        viable_places.sort(key=lambda p: self.spawn.distance_squared(p))
        place = viable_places[0]
        c.draw_indicator_dot(place, 0, 0, 0)

        if place in active_ends:
            self.current_target = None
            self.mode = 7 if not self.is_axionite_path else 0
            self.mode_after_barrier = 0
            self.pending_barriers_harvester = self._make_pending_barriers(
                c,
                viable_places,
                extra_places_for_turrent,
            )
            self.last_bridge_built_pos = None
            self.last_conveyor_pos = None
            self.last_path_built = None
            return

        if c.is_in_vision(place):
            if not self._clear_tile(c, place):
                return  # Aún no lo hemos roto

        if place == current:
            dir = self.navegador._any_free_dir(c, False, c.get_map_width(), c.get_map_height())
            move_pos = current.add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            self._try_move(c, dir)
            return

        if current.distance_squared(place) > 2:
            dir = self.navegador.moveTo(c, place, False)
            move_pos = current.add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            self._try_move(c, dir)
            return

        # --- Selección del destino ---
        nearby_builds = c.get_nearby_buildings()

        if self.bridge_destination is not None:
            end = self.bridge_destination
        else:
            target_end = self._find_best_bridge_end(place, c, nearby_builds)
            end = target_end
            if target_end is None:
                self.mode = 0
                self.current_target = None
                self.last_bridge_built_pos = None
                self.last_conveyor_pos = None
                self.last_path_built = None
                return

            # Para caminos de titanio: comprobar si conveyors son más baratas
            if not self.is_axionite_path:
                conv_path = _is_conv_better(c, place, target_end, self.layout_pos, self.layot_entity[2], self.layot_entity[4])
                self.conveyor_path = conv_path
                if conv_path is not None and len(conv_path) > 0:
                    conv_pos, conv_dir = conv_path[0]
                    if c.can_build_armoured_conveyor(conv_pos, conv_dir):
                        c.build_armoured_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    elif c.can_build_conveyor(conv_pos, conv_dir):
                        c.build_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    else:
                        self._try_mark_path_wip(c, conv_pos)
                    self.mode = 7 if not self.is_axionite_path else 4
                    self.mode_after_barrier = 4
                    self.pending_barriers_harvester = self._make_pending_barriers(
                        c,
                        viable_places,
                        extra_places_for_turrent,
                        reserved_positions=[conv_pos] + [pos for pos, _ in conv_path],
                    )
                    return

            c.draw_indicator_dot(target_end, 255, 255, 255)

        c.draw_indicator_dot(end, 255, 255, 255)

        # Quitar barrier propia en place si la hay
        building_id_place = c.get_tile_building_id(place)
        if (building_id_place is not None
                and c.get_entity_type(building_id_place) == EntityType.BARRIER
                and c.get_team(building_id_place) == c.get_team()):
            if c.can_destroy(place):
                c.destroy(place)

        if c.can_build_bridge(place, end):
            c.build_bridge(place, end)
            self.last_path_built = place
            self.last_bridge_end = end
            self.last_bridge_built_pos = place
            self.bridge_destination = None
            self.bridge_origin = None

            # Para caminos de axionita: programar colocación del marker en turno siguiente
            if self.is_axionite_path:
                self.pending_axionite_marker = place

            if end in active_ends:
                self.current_target = None
                self.mode = 7 if not self.is_axionite_path else 0
                self.mode_after_barrier = 0
                self.pending_barriers_harvester = self._make_pending_barriers(
                    c,
                    viable_places,
                    extra_places_for_turrent,
                    reserved_positions=[place],
                )
                self.last_bridge_end = None
                self.last_bridge_built_pos = None
                self.last_conveyor_pos = None
                self.last_path_built = None
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR)
                  and c.get_team() == c.get_team(c.get_tile_building_id(end))):
                self.mode = 7 if not self.is_axionite_path else 3
                self.mode_after_barrier = 3
                self.pending_barriers_harvester = self._make_pending_barriers(
                    c,
                    viable_places,
                    extra_places_for_turrent,
                    reserved_positions=[place],
                )
            else:
                self.mode = 7 if not self.is_axionite_path else 2
                self.mode_after_barrier = 2
                self.pending_barriers_harvester = self._make_pending_barriers(
                    c,
                    viable_places,
                    extra_places_for_turrent,
                    reserved_positions=[place],
                )
        else:
            if self._try_mark_path_wip(c, place):
                if c.is_in_vision(place):
                    mark = c.get_tile_building_id(place)
                    val = c.get_marker_value(mark)
                    if c.get_id() != _get_wip_marker_id(val):
                        self.mode = 0
                        self.last_bridge_built_pos = None
                        self.last_conveyor_pos = None
                        self.last_path_built = None
                        self.current_target = None
                        return

    # MODE 2

    def bridgeHome(self, c: Controller):
        current = c.get_position()
        bridge_end = self.last_bridge_end

        # ── Detección de torreta enemiga en la siguiente casilla (modo 2) ────────
        if c.is_in_vision(bridge_end) and not self.is_axionite_path:
            next_bid = c.get_tile_building_id(bridge_end)
            if (next_bid is not None
                    and c.get_entity_type(next_bid) in (
                        EntityType.GUNNER, EntityType.SENTINEL,
                        EntityType.BREACH, EntityType.LAUNCHER)
                    and c.get_team(next_bid) != c.get_team()):
                threat = self._find_enemy_threat(c)   # reutilizamos tu lógica existente
                if threat is not None:
                    self.last_bridge_end = self.last_path_built

                    self._mode5_prev_mode    = self.mode
                    self._mode5_threat_pos   = threat
                    self._mode5_absent_turns = 0
                    self._mode5_gone_since   = 0
                    self._mode5_sentinel_pos = None
                    self.mode = 5

                    c.draw_indicator_dot(current, 255, 20, 147)
                    self.defend_sentinel(c)
                    return
        
        if c.is_in_vision(bridge_end):
            next_bid = c.get_tile_building_id(bridge_end)
            if next_bid is not None and c.get_team() == c.get_team(next_bid) and c.get_entity_type(next_bid) in TRANSPORT_TYPES:
                self.mode = 3
                return

                
        active_ends = self._active_ends
        self.reserved = False

        if bridge_end is not None and bridge_end in active_ends:
            self.mode = 0
            self.last_bridge_end = None
            self.last_bridge_built_pos = None
            self.last_conveyor_pos = None
            self.last_path_built = None
            self.current_target = None
            return

        # Moverse hasta anchor
        if current != bridge_end and current.distance_squared(bridge_end) > 2:
            dir = self.navegador.moveTo(c, bridge_end, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return

        # En anchor — colocar siguiente puente
        nearby_builds = c.get_nearby_buildings()

        if self.bridge_destination is not None:
            end = self.bridge_destination
        else:
            target_end = self._find_best_bridge_end(bridge_end, c, nearby_builds)

            if target_end is None:
                dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
                next_pos = current.add(dir)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir)
                return

            c.draw_indicator_dot(target_end, 255, 255, 0) # Amarillo

            # Para caminos de titanio: comprobar si conveyors son más baratas
            if not self.is_axionite_path:
                conv_path = _is_conv_better(c, bridge_end, target_end, self.layout_pos, self.layot_entity[2], self.layot_entity[4])
                self.conveyor_path = conv_path
                if conv_path is not None and len(conv_path) > 0:
                    conv_pos, conv_dir = conv_path[0]
                    if c.can_build_armoured_conveyor(conv_pos, conv_dir):
                        c.build_armoured_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    elif c.can_build_conveyor(conv_pos, conv_dir):
                        c.build_conveyor(conv_pos, conv_dir)
                        self.conveyor_path.pop(0)
                        self.last_bridge_end = conv_pos.add(conv_dir)
                        self.last_conveyor_dir = conv_dir
                    else:
                        self._try_mark_path_wip(c, conv_pos)
                    self.mode = 4
                    return
            end = target_end

        if c.is_in_vision(bridge_end):
            if not self._clear_tile(c, bridge_end):
                return  # Aún no lo hemos roto

        # Quitar barrier propia en bridge_end si la hay
        building_id_be = c.get_tile_building_id(bridge_end) # Should not happen
        if (building_id_be is not None
                and c.get_entity_type(building_id_be) == EntityType.BARRIER
                and c.get_team(building_id_be) == c.get_team()):
            if c.can_destroy(bridge_end):
                c.destroy(bridge_end)
            return

        # si no hay conveyor, comportamiento normal
        if c.can_build_bridge(bridge_end, end):
            c.build_bridge(bridge_end, end)
            self.last_path_built = bridge_end
            self.last_bridge_end = end
            self.last_bridge_built_pos = bridge_end
            self.bridge_destination = None
            self.bridge_origin = None

            # Para caminos de axionita: programar colocación del marker en turno siguiente
            if self.is_axionite_path:
                self.pending_axionite_marker = bridge_end

            if end in active_ends:
                self.mode = 0
                self.last_bridge_end = None
                self.last_bridge_built_pos = None
                self.last_conveyor_pos = None
                self.last_path_built = None
                self.current_target = None
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR)
                  and c.get_team() == c.get_team(c.get_tile_building_id(end))):
                self.mode = 3
            else:
                self.mode = 2
        else:
            if self._try_mark_path_wip(c, bridge_end):
                if c.is_in_vision(bridge_end):
                    mark = c.get_tile_building_id(bridge_end)
                    val = c.get_marker_value(mark)
                    if c.get_id() != _get_wip_marker_id(val):
                        self.mode = 0
                        self.last_bridge_built_pos = None
                        self.last_conveyor_pos = None
                        self.last_path_built = None
                        self.current_target = None
                        return

    # MODE 3

    def revisar_camino_casa(self, c: Controller):
        current = c.get_position()

        if self.check_pos is None:
            self.check_pos = self.last_bridge_end

        if self.check_pos is None: # No debería pasar?
            self.mode = 0
            self.last_bridge_built_pos = None
            self.last_conveyor_pos = None
            self.last_path_built = None
            self.current_target = None
            return

        if self.check_pos in self.end_bridges_titanium:
            self.mode = 0
            self.check_pos = None
            self.last_bridge_end = None
            self.last_bridge_built_pos = None
            self.last_conveyor_pos = None
            self.last_path_built = None
            self.current_target = None
            return

        c.draw_indicator_dot(self.check_pos, 255, 128, 0) # Naranja

        if not c.is_in_vision(self.check_pos):
            dir = self.navegador.moveTo(c, self.check_pos, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)

        if not c.is_in_vision(self.check_pos):
            return

        building_id = c.get_tile_building_id(self.check_pos)
        entity = c.get_entity_type(building_id)

        if building_id is None:
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return

        if c.get_team(building_id) != c.get_team():
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return
        
        if ((entity == EntityType.MARKER and _is_wip_marker(c.get_marker_value(building_id)))
             or (entity == EntityType.BARRIER)
             or (entity in (EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER))):
            self.mode = 0
            self.check_pos = None
            self.last_bridge_end = None
            self.last_bridge_built_pos = None
            self.last_conveyor_pos = None
            self.last_path_built = None
            self.current_target = None
            return
        
        if entity not in TRANSPORT_TYPES:
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return

        next_check = None
        if entity == EntityType.BRIDGE:
            next_check = c.get_bridge_target(building_id)
        elif entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            next_check = self.check_pos.add(c.get_direction(building_id))
        else:
            # Es un splitter
            d = c.get_direction(building_id)
            possible_dirs = [d, d.rotate_left().rotate_left(), d.rotate_right().rotate_right()]
            out_of_vision_fallback = None
            for dir in possible_dirs:
                ck_pos = self.check_pos.add(dir)
                if not self._in_bounds(ck_pos):
                    continue
                if not c.is_in_vision(ck_pos):
                    out_of_vision_fallback = ck_pos
                    continue
                if c.get_tile_env(ck_pos) == Environment.WALL:
                    continue

                bid = c.get_tile_building_id(ck_pos)
                etype = c.get_entity_type(bid)
                if etype in TRANSPORT_TYPES and c.get_team() == c.get_team(bid):
                    if etype in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR):
                        b_dir = c.get_direction(bid)
                        if b_dir == ck_pos.direction_to(self.check_pos):
                            continue
                    elif etype == EntityType.SPLITTER:
                        b_dir = c.get_direction(bid)
                        if b_dir.opposite() == ck_pos.direction_to(self.check_pos):
                            continue
                    elif etype == EntityType.BRIDGE:
                        targ = c.get_bridge_target(bid)
                        if targ == self.check_pos:
                            continue
                    next_check = ck_pos
                    break
                elif c.is_tile_passable(ck_pos):
                    next_check = ck_pos
                

            if next_check is None:
                next_check = out_of_vision_fallback

        if next_check is None:
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return

        self.check_pos = next_check

    # MODE 4

    def place_conveyors(self, c: Controller):
        """
        Coloca conveyor a conveyor siguiendo self.conveyor_path (lista de (pos, dir)).
        Al terminar, vuelve a self.mode_after_conv.
        """
        if not self.conveyor_path: #No debería ocurrir casi Nunca?
            self._check_conveyor_chain_end(c, self.last_bridge_end)
            return

        current = c.get_position()
        conv_pos, conv_dir = self.conveyor_path[0]

        if conv_pos is None or conv_dir is None:
            #espero q no pase
            pass

        # ── Detección de torreta enemiga en la siguiente casilla (modo 4) ────────
        if c.is_in_vision(conv_pos) and not self.is_axionite_path:
            next_bid = c.get_tile_building_id(conv_pos)
            if (next_bid is not None
                    and c.get_entity_type(next_bid) in (
                        EntityType.GUNNER, EntityType.SENTINEL,
                        EntityType.BREACH, EntityType.LAUNCHER)
                    and c.get_team(next_bid) != c.get_team()):
                threat = self._find_enemy_threat(c)   # reutilizamos tu lógica existente
                if threat is not None:
                    self.conveyor_path.insert(0,(self.last_conveyor_pos, self.last_conveyor_dir))
                    self.last_bridge_end = self.last_conveyor_pos if self.last_conveyor_pos is not None else self.last_path_built

                    self._mode5_prev_mode    = self.mode
                    self._mode5_threat_pos   = conv_pos
                    self._mode5_absent_turns = 0
                    self._mode5_gone_since   = 0
                    self._mode5_sentinel_pos = None
                    self.mode = 5

                    c.draw_indicator_dot(current, 255, 20, 147)
                    self.defend_sentinel(c)
                    return
                
        if c.is_in_vision(conv_pos):
            next_bid = c.get_tile_building_id(conv_pos)
            if next_bid is not None and c.get_team() == c.get_team(next_bid) and c.get_entity_type(next_bid) in TRANSPORT_TYPES:
                self.mode = 3
                return

        # Azul Oscuro
        c.draw_indicator_dot(conv_pos, 26, 42, 219)
        c.draw_indicator_line(current, conv_pos, 26, 42, 219)

        # ── Acercarnos si estamos lejos ──────────────────────────────────────────
        if current.distance_squared(conv_pos) > 2:
            dir = self.navegador.moveTo(c, conv_pos, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return

        # ── Inspeccionar la casilla ──────────────────────────────────────────────
        if c.is_in_vision(conv_pos):
            build_id = c.get_tile_building_id(conv_pos)
            if build_id is not None:
                entity = c.get_entity_type(build_id)
                team = c.get_team(build_id)

                # Ya hay un conveyor/armoured aliado apuntando en la dirección correcta: saltar
                if (entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
                        and team == c.get_team()
                        and c.get_direction(build_id) == conv_dir):
                    self.last_conveyor_dir = conv_dir
                    self.conveyor_path.pop(0)
                    end = conv_pos.add(conv_dir)
                    self._check_conveyor_chain_end(c, end)
                    return

                # Si hay infraestructura de transporte aliada, no destruirla
                if (team == c.get_team() and entity in (
                        EntityType.BRIDGE, EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER)):

                    if (entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR)
                        and team == c.get_team()
                        and c.get_direction(build_id) == conv_dir) or entity not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):

                        self.conveyor_path.pop(0)
                        if entity == EntityType.BRIDGE:
                            end = c.get_bridge_target(build_id)
                        else:
                            end = conv_pos.add(c.get_direction(build_id))
                        if end is not None:
                            self.last_bridge_end = end
                            self._check_conveyor_chain_end(c, end)
                        return

                # Cualquier otro edificio: intentar limpiar
                if not self._clear_tile(c, conv_pos):
                    return

        # ── Construir el conveyor (preferir armoured si hay recursos) ────────────
        built = False
        if c.can_build_armoured_conveyor(conv_pos, conv_dir):
            c.build_armoured_conveyor(conv_pos, conv_dir)
            built = True
        elif c.can_build_conveyor(conv_pos, conv_dir):
            c.build_conveyor(conv_pos, conv_dir)
            built = True

        if built:
            self.last_path_built = conv_pos
            self.last_conveyor_pos = conv_pos
            self.last_conveyor_dir = conv_dir
            self.conveyor_path.pop(0)
            end = conv_pos.add(conv_dir)
            self.last_bridge_end = end
            self._check_conveyor_chain_end(c, end)
        else:
            if self._try_mark_path_wip(c, conv_pos):
                if c.is_in_vision(conv_pos):
                    mark = c.get_tile_building_id(conv_pos)
                    val = c.get_marker_value(mark)
                    if c.get_id() != _get_wip_marker_id(val):
                        self.mode = 0
                        self.last_bridge_built_pos = None
                        self.last_conveyor_pos = None
                        self.last_path_built = None
                        self.current_target = None
                        return

    def _check_conveyor_chain_end(self, c: Controller, end: Position):
        """
        Tras colocar (o saltar) un conveyor, comprueba si `end` ya es un nodo
        base o si la cadena está terminada, y actualiza el modo.
        """
        if end in self._active_ends:
            self.conveyor_path = []
            self.mode = 0
            self.last_bridge_end = None
            self.last_bridge_built_pos = None
            self.last_conveyor_pos = None
            self.last_path_built = None
            self.current_target = None
            self.last_conveyor_dir = None
            return

        if not self.conveyor_path:
            self.last_conveyor_dir = None
            if c.is_in_vision(end):
                end_bid = c.get_tile_building_id(end)
                if (end_bid is not None
                        and c.get_team(end_bid) == c.get_team()
                        and c.get_entity_type(end_bid) in (
                            EntityType.BRIDGE,
                            EntityType.CONVEYOR,
                            EntityType.ARMOURED_CONVEYOR,
                            EntityType.SPLITTER)):
                    self.mode = 3
                    return
            self.mode = 2

    # =========================================================================
    # MODE 5: Defender ruta con sentinel
    # =========================================================================

    _SENTINEL_ABSENT_THRESHOLD = 5   # turnos sin ver al enemigo antes de salir

    def _find_enemy_threat(self, c: Controller) -> "Position | None":
        """
        Devuelve la posición del primer bot o torreta enemiga visible,
        o None si no hay ninguno en visión.
        Tipos de torreta considerados: GUNNER, SENTINEL, BREACH, LAUNCHER.
        """
        turret_types = (
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
            EntityType.LAUNCHER,
        )
        for eid in c.get_nearby_entities():
            if c.get_team(eid) == c.get_team():
                continue
            et = c.get_entity_type(eid)
            if et in turret_types:
                return c.get_position(eid)
        return None

    def defend_sentinel(self, c: Controller):
        """
        Modo 5 — Defensa con sentinel.

        Flujo por tick:
        1. Comprobar si la amenaza sigue visible y actualizar contador de ausencia.
        2. Si lleva ≥ _SENTINEL_ABSENT_THRESHOLD turnos sin verse Y ya no hay
           ningún otro enemigo visible → limpiar sentinel y volver al modo previo.
        3. Si aún no hemos construido el sentinel:
           a. Calcular si desde last_bridge_end el sentinel puede atacar la amenaza
              (usando can_fire_from con todas las direcciones cardinales/diagonales).
           b. Si puede → acercarse a last_bridge_end y construirlo.
           c. Si no puede → esperar quieto (ya estamos en zona segura; el sentinel
              en otro sitio no serviría de nada con la info actual).
        4. Si ya tenemos sentinel → vigilar (nada que hacer, el sentinel actúa solo).
        """
        current      = c.get_position()
        sentinel_pos = self.last_bridge_end

        # ── 1. Actualizar visibilidad de la amenaza ──────────────────────────
        new_threat = self._find_enemy_threat(c)
        if new_threat is not None:
            self._mode5_threat_pos   = new_threat
            self._mode5_absent_turns = 0
            self._mode5_gone_since   = 0
        else:
            self._mode5_absent_turns += 1

        # ── 2. Comprobar condición de salida ─────────────────────────────────
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
            # Solo salimos si ya no hay sentinel pendiente de destruir
            if self._mode5_sentinel_pos is None:
                self.mode = self._mode5_prev_mode
                self._mode5_threat_pos   = None
                self._mode5_absent_turns = 0
            return

        # ── 3. Si ya tenemos sentinel construido → vigilar o reorientar ──────
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
                        sp, sentinel_facing,
                        EntityType.SENTINEL, self._mode5_threat_pos
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

        # ── 4. Aún no hemos construido el sentinel ───────────────────────────
        if sentinel_pos is None or self._mode5_threat_pos is None:
            return

        c.draw_indicator_dot(sentinel_pos, 133, 8, 119)

        # Calcular dirección prohibida (conveyor que alimenta sentinel_pos)
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

        # Buscar la mejor dirección para el sentinel
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
            if self._mode5_threat_pos is not None:
                c.draw_indicator_line(current, self._mode5_threat_pos, 255, 100, 100)
            return

        # Acercarnos a sentinel_pos
        if current.distance_squared(sentinel_pos) > 2:
            dir_ = self.navegador.moveTo(c, sentinel_pos, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)
            return

        # ── Gestión de la casilla con barrier/clear diferido ──────────
        bid = c.get_tile_building_id(sentinel_pos)
        
        # Comprobamos si ya tenemos una barrier nuestra de reserva ahí
        our_barrier_there = (
            bid is not None
            and c.get_entity_type(bid) == EntityType.BARRIER
            and c.get_team(bid) == c.get_team()
            and self._mode5_barrier_pos == sentinel_pos
        )

        if our_barrier_there and c.get_global_resources()[0] >= c.get_sentinel_cost()[0]:
            
            if not self._clear_tile(c, sentinel_pos):
                return
            # Tile libre: poner sentinel si tenemos recursos, o barrier de reserva
            if current == sentinel_pos:
                dir_ = self.navegador._any_free_dir(c, False, c.get_map_width(), c.get_map_height())
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir_)

            if c.can_build_sentinel(sentinel_pos, best_dir):
                self._mode5_barrier_pos = None
                # Tras destroy, el tile queda libre: construir el sentinel
                c.build_sentinel(sentinel_pos, best_dir)
                self._mode5_sentinel_pos = sentinel_pos
                if self._mode5_threat_pos is not None:
                    c.draw_indicator_line(sentinel_pos, self._mode5_threat_pos, 255, 20, 147)
            return

        # No hay barrier nuestra: gestionar lo que haya en el tile
        if bid is not None:
            et = c.get_entity_type(bid)
            if et == EntityType.SENTINEL and c.get_team(bid) == c.get_team():
                self._mode5_sentinel_pos = sentinel_pos
                return
            if our_barrier_there:
                return

        if c.get_global_resources()[0] < c.get_barrier_cost()[0] or not self._clear_tile(c, sentinel_pos):
            return
        # Tile libre: poner sentinel si tenemos recursos, o barrier de reserva
        if current == sentinel_pos:
            dir_ = self.navegador._any_free_dir(c, False, c.get_map_width(), c.get_map_height())
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)

        if c.can_build_barrier(sentinel_pos):
            c.build_barrier(sentinel_pos)
            self._mode5_barrier_pos = sentinel_pos
        # Si no tenemos recursos para barrier, esperamos sin limpiar
        return

    # =========================================================================
    # HELPERS DE DETECCIÓN DE CADENAS ROTAS
    # =========================================================================

    def _transport_output_pos(self, c: Controller, bid: int, pos: Position) -> Position | None:
        """
        Devuelve la posición de salida de un nodo de transporte aliado.
        Para bridges: get_bridge_target.
        Para conveyor/armoured_conveyor: pos + dirección.
        Para splitter: None (salida múltiple, no la rastreamos en modo 6).
        """
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
        """
        Devuelve True si el output del nodo en `pos` está roto:
          - output_pos existe pero está vacío (sin edificio aliado de transporte),
          - y NO es un nodo base (_active_ends / layout_pos).
        Solo se evalúa si output_pos está en visión.
        """
        output = self._transport_output_pos(c, bid, pos)
        if output is None:
            return False
        if not self._in_bounds(output):
            return False
        if output in self._active_ends or output in self.layout_pos:
            return False
        if not c.is_in_vision(output):
            return False  # no podemos confirmar rotura sin verlo

        out_bid = c.get_tile_building_id(output)
        if out_bid is None:
            return True  # casilla vacía → roto
        out_et = c.get_entity_type(out_bid)
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
            return True  # hay algo, pero no es transporte → roto
        return False

    def _scan_broken_chains(self, c: Controller) -> tuple[Position, Position] | None:
        """
        Escanea los edificios de transporte aliados visibles en busca del primer
        nodo cuyo output esté roto.

        Devuelve (broken_pos, upstream_pos) donde:
          - broken_pos   = posición del nodo roto (donde hay que retomar desde modo 2).
          - upstream_pos = posición del nodo anterior en la cadena (punto de partida
                           del rastreo upstream en modo 6); si no hay upstream visible,
                           devuelve broken_pos como punto de partida.

        Devuelve None si no se detecta ninguna cadena rota.

        Estrategia de rastreo upstream:
          Para encontrar el nodo que alimenta a broken_pos buscamos en el vecindario
          inmediato (dist² ≤ 9) un nodo de transporte aliado cuyo output apunte
          exactamente a broken_pos.
        """

        for b in c.get_nearby_buildings():
            if c.get_team(b) != c.get_team():
                continue
            et = c.get_entity_type(b)
            if et not in TRANSPORT_TYPES:
                continue
            bpos = c.get_position(b)
            if bpos in self.layout_pos:
                continue  # nodo base del layout — ignorar

            if not self._chain_output_is_broken(c, b, bpos):
                continue

            # Roto encontrado: buscar el nodo upstream (el que alimenta bpos)
            upstream = bpos  # por defecto empezamos desde el nodo roto mismo
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
                    nb_et = c.get_entity_type(nb_bid)
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

    # =========================================================================
    # MODE 6: Rastrear cadena rota upstream hasta el harvester
    # =========================================================================

    def repair_broken_chain(self, c: Controller):
        """
        Modo 6: sigue la cadena de transporte aliada hacia atrás (upstream)
        desde _repair_chain_pos hasta encontrar el harvester fuente.

        Mientras _repair_chain_pos está fuera de visión, el bot se mueve
        hacia esa posición. Una vez en visión, busca el nodo anterior en la
        cadena (el que apunta a _repair_chain_pos) y avanza un paso upstream.

        Cuando encontramos un harvester aliado:
          - current_target = posición del harvester
          - last_bridge_end = _repair_broken_pos  (retomar construcción desde aquí)
          - is_axionite_path según el tipo de ore del harvester
          - mode = 2  (bridgeHome retoma el camino)

        Si en algún momento perdemos la pista (no hay nodo upstream visible),
        volvemos a modo 2 directamente usando _repair_broken_pos.
        """
        current = c.get_position()

        # Sanity: si no hay estado de reparación, volver a modo 0
        if self._repair_broken_pos is None:
            self.mode = 0
            return

        chain_pos = self._repair_chain_pos
        if chain_pos is None:
            chain_pos = self._repair_broken_pos

        c.draw_indicator_dot(chain_pos, 0, 200, 255)
        c.draw_indicator_line(current, chain_pos, 0, 200, 255)

        # ── 1. Moverse hasta tener chain_pos en visión ───────────────────────
        if not c.is_in_vision(chain_pos):
            dir_ = self.navegador.moveTo(c, chain_pos, four_dirs=False)
            next_pos = current.add(dir_)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir_)
            return

        # chain_pos está en visión — inspeccionarla
        bid = c.get_tile_building_id(chain_pos)

        # ── 2. Casilla vacía o sin transporte aliado: cadena perdida ─────────
        if bid is None or c.get_team(bid) != c.get_team():
            # No hay nada aquí; retomamos construcción desde broken_pos
            self._commit_repair(c)
            return

        et = c.get_entity_type(bid)

        # ── 3. ¡Encontramos el harvester! ────────────────────────────────────
        if et == EntityType.HARVESTER:
            self._repair_harvester = chain_pos
            ore_env = c.get_tile_env(chain_pos)
            self.is_axionite_path = (ore_env == Environment.ORE_AXIONITE)
            self.current_target = chain_pos
            self.last_bridge_end = self._repair_broken_pos
            self.last_path_built = self._repair_broken_pos
            self._repair_broken_pos = None
            self._repair_chain_pos  = None
            self._repair_harvester  = None
            self.mode = 2
            return

        # ── 4. Es un nodo de transporte aliado: avanzar un paso upstream ─────
        if et not in TRANSPORT_TYPES:
            # Estructura aliada no-transporte: cadena perdida
            self._commit_repair(c)
            return

        # Buscar el nodo upstream: aquel cuyo output apunta a chain_pos
        # Buscamos en un radio dist² ≤ 9 centrado en chain_pos
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
                # El harvester sería el nodo fuente final
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
            # Avanzar un paso upstream
            self._repair_chain_pos = upstream_found
            # Llamada recursiva inmediata si ya está en visión (evita tick perdido)
            if c.is_in_vision(upstream_found):
                self.repair_broken_chain(c)
            else:
                dir_ = self.navegador.moveTo(c, upstream_found, four_dirs=False)
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir_)
        else:
            # Ningún nodo upstream visible: movernos hacia chain_pos para ver más
            # Si ya estamos adyacentes y no vemos nada, la cadena está perdida
            if current.distance_squared(chain_pos) <= 2:
                self._commit_repair(c)
            else:
                dir_ = self.navegador.moveTo(c, chain_pos, four_dirs=False)
                next_pos = current.add(dir_)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir_)

    def _commit_repair(self, c: Controller):
        """
        No pudimos encontrar el harvester fuente. Retomamos la construcción
        desde _repair_broken_pos directamente usando el modo 2 normal.
        """
        if self._repair_broken_pos is not None:
            self.last_bridge_end = self._repair_broken_pos
            self.last_path_built = self._repair_broken_pos
        self._repair_broken_pos = None
        self._repair_chain_pos  = None
        self._repair_harvester  = None
        self.mode = 2

    # MODE 7

    def barrier_harvester(self, c: Controller):
        if len(self.pending_barriers_harvester) == 0:
            self.mode = self.mode_after_barrier
            return
        
        current = c.get_position()
        pending = list(self.pending_barriers_harvester)
        pending.sort(key=lambda p: current.distance_squared(p), reverse=True)
        
        target = pending[0]
        dist = current.distance_squared(target)
        if dist > 2:
            dir = self.navegador.moveTo(c, target, False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)

        if not c.is_in_vision(target):
            return

        if not self._clear_tile(c, target):
            return
        
        if dist == 0:
            dir = self.navegador._any_free_dir(c, False, c.get_map_width(), c.get_map_height())
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
        
        if c.can_build_barrier(target):
            c.build_barrier(target)
            pending.pop(0)
            self.pending_barriers_harvester = set(pending)
            if len(self.pending_barriers_harvester) == 0:
                self.mode = self.mode_after_barrier

    # UTILITY

    def construir(self, c: Controller, objetivo: Position, edificio: EntityType) -> bool:
        """
        Intenta construir 'edificio' en 'objetivo'.

        Devuelve True  cuando la casilla está "resuelta" (construida o saltada definitivamente).
        Devuelve False cuando necesita más turnos (hay que volver a llamar el siguiente tick).
        """
        current = c.get_position()
        building_id = c.get_tile_building_id(objetivo)

        # ── 1. Ya está construido lo que queremos ────────────────────────────────
        if building_id is not None:
            entity = c.get_entity_type(building_id)
            team = c.get_team(building_id)

            if entity == edificio and team == c.get_team():
                return True  # Ya existe; nada que hacer

            # ── 2. Road propia: destruir y esperar al turno siguiente ────────────
            if entity == EntityType.ROAD and team == c.get_team():
                if current.distance_squared(objetivo) > 2:
                    if not self.navegador.is_reachable(c, objetivo):
                        return True  # skip permanente: inalcanzable
                    c.draw_indicator_line(current, objetivo, 0, 100, 0)
                    dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    self._try_move(c, dir)
                    return False  # Nos acercamos primero

                if c.can_destroy(objetivo):
                    c.destroy(objetivo)
                return False  # El turno siguiente la casilla estará vacía

            # ── 3. Road enemiga: ponerse encima y atacar ─────────────────────────
            if entity == EntityType.ROAD and team != c.get_team():
                if current != objetivo:
                    if c.is_tile_passable(objetivo):
                        c.draw_indicator_line(current, objetivo, 0, 100, 0)
                        dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                        next_pos = current.add(dir)
                        if c.can_build_road(next_pos):
                            c.build_road(next_pos)
                        self._try_move(c, dir)
                    return False  # Aún no estamos encima

                # Estamos encima: atacar
                if c.can_fire(objetivo):
                    c.fire(objetivo)

                # Si se destruyó, salir a una casilla adyacente para poder construir
                if c.get_tile_building_id(objetivo) is None:
                    for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
                        adj = objetivo.add(d)
                        if self._in_bounds(adj):
                            if self._try_move(c, d):
                                break

                return False  # El turno siguiente construiremos

            # ── 5. Cualquier otro edificio: skip permanente ──────────────────────
            return True

        # ── 4. Casilla vacía: acercarse y construir ──────────────────────────────
        if current.distance_squared(objetivo) > 2:
            c.draw_indicator_line(current, objetivo, 0, 100, 0)
            dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return False

        if current == objetivo:
            dir = self.navegador._any_free_dir(c, False, c.get_map_width(), c.get_map_height())
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)

        # En rango: construir según el tipo de edificio
        if edificio == EntityType.BARRIER and c.can_build_barrier(objetivo):
            c.build_barrier(objetivo)
            return True

        if edificio == EntityType.SENTINEL:
            dir_torreta = objetivo.direction_to(self.last_bridge_built_pos)
            dir_harvester = objetivo.direction_to(self.current_target)
            c.draw_indicator_dot(objetivo, 0, 200, 0)
            c.draw_indicator_dot(self.current_target, 0, 100, 0)
            c.draw_indicator_dot(self.last_bridge_built_pos, 200, 200, 0)
            if dir_torreta == dir_harvester:
                dir_torreta = dir_torreta.rotate_left()
            if c.can_build_sentinel(objetivo, dir_torreta):
                c.build_sentinel(objetivo, dir_torreta)
                self.sentinel_placed = True
                return True

        return False

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        """
        Intenta eliminar lo que haya en `target`.
        - Aliado: c.destroy() si estamos a distancia² <= 2.
        - Enemigo: c.fire() solo si estamos encima (distancia² == 0).

        Devuelve True si el tile ya está despejado (no hay nada),
        False si aún queda algo (o no podemos actuar todavía).
        """
        building_id = c.get_tile_building_id(target)
        if building_id is None:
            return True  # ya está libre

        current = c.get_position()
        is_ally = c.get_team(building_id) == c.get_team()

        if is_ally:
            if c.can_destroy(target):
                c.destroy(target)
                return True
            # Nos acercamos para poder destruirlo (necesita dist² <= 2)
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return False
        else:
            # Enemigo: necesitamos estar encima
            if current == target:
                if c.can_fire(target):
                    c.fire(target)
                    return c.get_tile_building_id(target) is None
                return False
            else:
                # Movernos encima si es posible
                if c.is_tile_passable(target):
                    dir = self.navegador.moveTo(c, target, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    self._try_move(c, dir)
                return False
    
    def place_axionite_marker(self, c: Controller):
        current = c.get_position()
        # ── Marker de axionita pendiente ─────────────────────────────────────────
        # Buscamos la mejor casilla adyacente al bridge (dist² ≤ 2) con env EMPTY:
        #   Prioridad 1: sin building (ideal) — más cercana al bot primero
        #   Prioridad 2: building propia de tipo ROAD — la destruiremos
        #   Prioridad 3: building enemiga passable — _clear_tile la elimina
        # Nos acercamos a esa casilla (dist² ≤ 2 desde el bot para place_marker),
        # limpiamos con _clear_tile() si tiene algo, y bloqueamos el turno.
        if self.pending_axionite_marker is not None:
            bridge_pos = self.pending_axionite_marker

            # ── 1. Calcular la mejor casilla para el marker ──────────────────────
            # Candidatos: todas las casillas con dist² ≤ 2 del bridge (sin incluir
            # el bridge mismo). Clasificamos en tres niveles de prioridad y dentro
            # de cada nivel preferimos la más cercana al bot actual.
            best_empty: tuple | None = None   # (dist_sq_bot, pos) — sin building
            best_road:  tuple | None = None   # (dist_sq_bot, pos) — road propia
            best_pass:  tuple | None = None   # (dist_sq_bot, pos) — passable enemigo

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
                    bid = c.get_tile_building_id(cand)
                    if bid is None:
                        # Casilla vacía — ideal
                        if best_empty is None or dist_bot < best_empty[0]:
                            best_empty = (dist_bot, cand)
                    else:
                        et = c.get_entity_type(bid)
                        tm = c.get_team(bid)
                        if tm == c.get_team() and et == EntityType.ROAD:
                            # Road propia — destruible
                            if best_road is None or dist_bot < best_road[0]:
                                best_road = (dist_bot, cand)
                        elif c.is_tile_passable(cand) and tm != c.get_team():
                            # Passable enemigo — _clear_tile puede eliminarlo
                            if best_pass is None or dist_bot < best_pass[0]:
                                best_pass = (dist_bot, cand)

            chosen = best_empty or best_road or best_pass
            marker_spot: Position | None = chosen[1] if chosen is not None else None

            if marker_spot is None:
                # Ninguna casilla válida visible — esperar sin bloquear el turno
                pass
            else:
                # ── 2. Acercarnos a marker_spot si estamos lejos ─────────────────
                # place_marker requiere que el bot esté a dist² ≤ 2 del destino.
                if current.distance_squared(marker_spot) > 2:
                    dir = self.navegador.moveTo(c, marker_spot, four_dirs=False)
                    self._try_move(c, dir)
                    return  # bloqueamos el resto del turno

                # ── 3. Limpiar casilla si tiene building ─────────────────────────
                if c.get_tile_building_id(marker_spot) is not None:
                    if not self._clear_tile(c, marker_spot):
                        return  # aún limpiando — bloquear turno

                # ── 4. Colocar marker ────────────────────────────────────────────
                marker_val = _encode_axionite_marker(bridge_pos)
                if c.can_place_marker(marker_spot):
                    c.place_marker(marker_spot, marker_val)
                    self.pending_axionite_marker = None
                # Si can_place_marker falla (cupo del turno ya usado), reintentamos
    
   # ── SCORING CONSTANTS ────────────────────────────────────────────────────────
    # Ajusta estos valores para calibrar el comportamiento sin tocar la lógica.

    # _MERGE_BONUS eliminado: el ahorro de conectarse a una cadena existente ya está
    # capturado en remaining_sq_desde_endpoint vs remaining_sq_desde_candidate.
    # Solo se añade un pequeño bonus fijo para desempatar a favor de reutilizar
    # infraestructura cuando la congestión es baja.
    _MERGE_TIEBREAK = 2     # bonus pequeño: preferir merge sobre casilla vacía equidistante
    _CARGO_PENALTY  = -200  # penalización si el nodo tiene material en storage

    # ── HELPERS ──────────────────────────────────────────────────────────────────
    def _chain_has_axionite(self, c: Controller, start_pos: Position, depth: int = 2) -> bool:
        """
        Recorre hacia adelante la cadena de transporte desde start_pos hasta
        `depth` saltos. Devuelve True si algún nodo lleva marker de axionita
        o almacena raw/refined axionite.
        """
        pos = start_pos
        visited = {pos}
        for _ in range(depth):
            if not c.is_in_vision(pos):
                break
            bid = c.get_tile_building_id(pos)
            if bid is None:
                break
            et = c.get_entity_type(bid)
            if c.get_team(bid) != c.get_team():
                break
            if et != EntityType.BRIDGE:
                if pos in self.end_bridges_axionite:
                    return self.is_axionite_path
                break
            # ¿Marker axionita en esta casilla?
            if _bridge_is_axionite_tagged(c, pos):
                return True
            # ¿Almacena axionita?
            try:
                stored = c.get_stored_resource(bid)
                if stored in (ResourceType.RAW_AXIONITE, ResourceType.REFINED_AXIONITE):
                    return True
            except Exception:
                pass
            # Avanzar
            nxt = None
            if et == EntityType.BRIDGE:
                try:
                    nxt = c.get_bridge_target(bid)
                except Exception:
                    pass
            elif et in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                try:
                    nxt = pos.add(c.get_direction(bid))
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
            end = None
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
                    False
            else:
                return False

    def _transport_congestion_penalty(
        self,
        bid: int,
        pos: "Position",
        get_cached,
    ) -> int:
        """
        Penalización de congestión — trabaja exclusivamente sobre `building_cache`,
        sin ninguna llamada a la API del Controller.

        building_cache: dict[Position -> (bid, entity_type, team, stored_resource, output_pos)]
          precalculado una sola vez en _find_best_bridge_end.

        Componentes:
          1. _CARGO_PENALTY si el propio nodo tiene material en storage.
          2. _CARGO_PENALTY * (vecinos_cargados / vecinos_conectados_total)
             Solo vecinos realmente conectados con `pos`:
               - Anterior: su output apunta a `pos` (nos alimenta).
               - Posterior: el output de `pos` apunta a ellos (los alimentamos).
        """

        penalty = 0

        # Datos del nodo evaluado desde la cache
        entry = get_cached(pos)
        if entry is None:
            return 0
        _, entity, team, stored, pos_output = entry

        # 1. Carga propia
        if stored is not None:
            penalty += self._CARGO_PENALTY

        # 2. Vecinos conectados
        total_connected  = 0
        loaded_connected = 0

        for ddx in range(-3, 4):
            for ddy in range(-3, 4):
                if ddx == 0 and ddy == 0:
                    continue
                nb = Position(pos.x + ddx, pos.y + ddy)
                nb_entry = get_cached(nb)
                if nb_entry is None:
                    continue
                _, nb_entity, nb_team, nb_stored, nb_output = nb_entry
                if nb_team != team:
                    continue
                if nb_entity not in TRANSPORT_TYPES:
                    continue

                # ¿Conectado?
                connected = False
                # a) nb envía hacia pos (anterior)
                if nb_output == pos:
                    connected = True
                # b) pos envía hacia nb (posterior)
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

    def _resolve_chain_endpoint(
        self,
        start_pos: "Position",
        start_bid: int,
        start_entity: "EntityType",
        get_cached,
    ) -> "Position":
        """
        Sigue la cadena de transporte aliada desde (start_pos, start_bid) usando
        building_cache exclusivamente (sin llamadas a la API).
        Devuelve la posición del último nodo alcanzable de la cadena, que puede
        ser un end_bridge o simplemente el nodo más lejano visible.
        """
        pos    = start_pos
        entity = start_entity
        bid    = start_bid
        visited = {pos}

        for _ in range(20):
            # Calcular salida de este nodo
            if entity == EntityType.BRIDGE:
                entry = get_cached(pos)
                nxt = entry[4] if entry else None          # output_pos precomputado
            elif entity in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                entry = get_cached(pos)
                nxt = entry[4] if entry else None
            else:
                break  # SPLITTER u otro: sin salida única conocida

            if nxt is None or nxt in visited:
                break

            # ¿Llegamos a un nodo base?
            if nxt in self._active_ends:
                return nxt

            nxt_entry = get_cached(nxt)
            if nxt_entry is None:
                break  # fuera de visión o casilla vacía: fin de cadena

            nxt_bid, nxt_et, nxt_team, _, _ = nxt_entry
            if nxt_team != get_cached(pos)[2]:  # distinto equipo
                break
            if nxt_et not in TRANSPORT_TYPES:
                break

            visited.add(nxt)
            pos    = nxt
            entity = nxt_et
            bid    = nxt_bid

        return pos   # último nodo alcanzable

    def _find_best_bridge_end(
        self,
        place: "Position",
        c: "Controller",
        builds: list,
    ) -> "Position | None":
        """
        Devuelve la mejor casilla destino (dist² ≤ 9 desde `place`) para el
        siguiente puente, fusionando la lógica de conexión a redes existentes
        con la búsqueda de paso óptimo hacia el nodo base más cercano.

        end_bridges son conveyors/splitters aliados junto al spawn. Un candidato
        que ya sea uno de esos nodos, o que pertenezca a una cadena conectada a
        uno, recibe MERGE_BONUS. La congestión lo penaliza.

        Score = -remaining_sq_to_nearest_end_bridge
              + dot_product          (desempate direccional)
              + MERGE_BONUS          (si conectado a base)
              + congestion_penalty   (cargo + vecinos extra)
        """
        import math as _math

        # ── Precalculate building cache (single API sweep) ───────────────────────
        # dict[Position -> (bid, entity_type, team, stored_resource, output_pos)]
        # Covers all visible tiles in vision radius so penalty needs 0 API calls.
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

            bid = c.get_tile_building_id(pos)
            if bid is None:
                building_cache[pos] = None
                return None

            et   = c.get_entity_type(bid)
            team = c.get_team(bid)

            stored = None
            try:
                stored = c.get_stored_resource(bid)
            except Exception:
                pass

            output = None
            if et == EntityType.BRIDGE:
                try:
                    output = c.get_bridge_target(bid)
                except Exception:
                    pass
            elif et in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                try:
                    output = pos.add(c.get_direction(bid))
                except Exception:
                    pass

            building_cache[pos] = (bid, et, team, stored, output)
            return building_cache[pos]


        # Objetivo final: nodo base más cercano distinto de last_bridge_end
        sorted_ends = sorted(self._active_ends, key=lambda p: place.distance_squared(p))
        final_target: "Position | None" = None
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
        best_score: float | None      = None

        # ── Candidatos: cuadrícula 7×7 centrada en place (dist² ≤ 9) ────────────
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
                if env in (
                    Environment.ORE_TITANIUM,
                    Environment.ORE_AXIONITE,
                    Environment.WALL,
                ):
                    continue

                merge_bonus    = 0
                congestion_pen = 0

                _cache_entry = get_cached(candidate)
                bid    = _cache_entry[0] if _cache_entry else None
                entity = _cache_entry[1] if _cache_entry else None
                team   = _cache_entry[2] if _cache_entry else None

                # Posición efectiva para remaining_sq: si el candidato es un
                # nodo de transporte aliado, seguimos su cadena hasta el
                # endpoint real para medir cuánto queda hasta la base.
                effective_end = candidate

                if bid is not None:
                    if team == c.get_team():
                        if entity in TRANSPORT_TYPES:
                            if entity == EntityType.BRIDGE:
                                # ── Comprobación de contaminación cruzada ──────────────────
                                # Un camino de axionita solo puede conectar a cadenas de axionita
                                # (identificadas por marker 833xxyy). Un camino de titanio nunca
                                # puede conectar a cadenas marcadas o que contengan axionita.
                                chain_is_axionite = _bridge_is_axionite_tagged(c, candidate) or \
                                                    self._chain_has_axionite(c, candidate)
                                if self.is_axionite_path and not chain_is_axionite and \
                                candidate not in self.end_bridges_axionite:
                                    continue  # ruta axionita no conecta a cadena sin marcador
                                if self.is_axionite_path and self._loops_to_me(c, bid) and \
                                candidate not in self.end_bridges_axionite:
                                    continue
                                if not self.is_axionite_path and chain_is_axionite:
                                    continue  # ruta titanio no conecta a cadena axionita
                                # Si is_axionite_path y chain_is_axionite → fluye normalmente con merge_bonus alto
                            elif self.is_axionite_path and candidate not in self.end_bridges_axionite:
                                continue
                            merge_bonus = 100 if (self.is_axionite_path) else self._MERGE_TIEBREAK

                            # Seguir cadena → endpoint real (todo en cache, 0 llamadas API)
                            effective_end = self._resolve_chain_endpoint(
                                candidate, bid, entity, get_cached
                            )
                            # Pequeño bonus de desempate por reutilizar infraestructura existente.
                            # La ganancia real ya está en effective_end más cercano a final_target.
                            congestion_pen = 0
                            if not self.is_axionite_path:
                                congestion_pen = self._transport_congestion_penalty(bid, candidate, get_cached)
                        elif entity == EntityType.CORE:
                            continue
                        elif not c.is_tile_passable(candidate) and c.get_tile_builder_bot_id(candidate) is None:
                            continue  # estructura aliada no transitable
                    else:
                        if not c.is_tile_passable(candidate):
                            continue  # estructura enemiga no transitable

                plus = 0
                if self.is_axionite_path and candidate in self.end_bridges_axionite:
                    plus = 200

                # remaining_sq desde el endpoint real de la cadena, no desde candidate
                remaining_sq = effective_end.distance_squared(final_target)
                dot          = ddx * ux + ddy * uy
                score        = -remaining_sq + dot + merge_bonus + congestion_pen + plus

                if best_score is None or score > best_score:
                    best_score = score
                    best_pos   = candidate

        return best_pos
