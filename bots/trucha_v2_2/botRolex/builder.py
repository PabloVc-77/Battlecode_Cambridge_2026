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
                if building_id is not None and c.get_entity_type(building_id) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER) and c.get_team(building_id) == c.get_team():
                    Existe = True
                    break
            else:
                Existe = True
                break
    return Existe

# ── Axionite bridge marker encoding ─────────────────────────────────────────
# Format: 833_xx_yy  →  integer = 833 * 10000 + x * 100 + y
# Works for map coordinates 0–99 in each axis.
_AXIONITE_MARKER_IDENT = 833

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

def _is_conv_better(c: Controller, ini: Position, end: Position, layout):
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

    transport_types = (
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.SPLITTER,
    )

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

            env = c.get_tile_env(neighbor)
            if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE, Environment.WALL):
                continue

            building_id = c.get_tile_building_id(neighbor)
            if building_id is not None:
                entity = c.get_entity_type(building_id)
                if entity == EntityType.ROAD:
                    pass  # tratar como casilla libre
                elif not (c.is_tile_passable(neighbor) and c.get_tile_builder_bot_id(neighbor) is None) and (entity != EntityType.BARRIER or c.get_team() != c.get_team(building_id)):
                    if neighbor != c.get_position() and entity not in transport_types:
                        continue
                elif entity in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR, EntityType.BRIDGE) and c.get_team() == c.get_team(building_id):
                    # Permitir si es el destino final, saltar si es nodo intermedio
                    if neighbor != end:
                        continue
                elif entity == EntityType.SPLITTER and c.get_team() == c.get_team(building_id):
                     # Permitir si es el destino final, saltar si es nodo intermedio
                    if neighbor != end or d != c.get_direction(building_id):
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
        self.conveyor_mode = False
        self.current_target = None

        self.conveyor_path = []      # lista de (pos, dir) para mode 4
        self.mode_after_conv = 2     # modo al que volver al terminar mode 4

        self.mode = 0
            # mode 0: Find Ore (Blanco)
            # mode 1: Place bridge near Ore (Verde)
            # mode 2: go home (Rojo)
            # mode 3: revisar estructura (Naranja)
            # mode 4: conveyor mode (Azul Oscuro)
            # mode 5: gunner junto con conveyors (Rosa)
        self.last_bridge_end = None
        self.last_bridge_built_pos = None
        self.check_pos = None

        # Variables de puentes
        self.bridge_origin = None         # casilla origen del puente pendiente de construir
        self.bridge_destination = None    # casilla destino del puente pendiente de construir

        self.turret_places = []

        # Mode 5 state
        self.mode5_splitter_pos: Position | None = None   # dónde poner el splitter
        self.mode5_splitter_dir: Direction | None = None  # dirección del splitter (=conv_dir)
        self.mode5_gunner_pos: Position | None = None     # dónde poner el gunner
        self.mode5_gunner_dir: Direction | None = None    # dirección del gunner
        self.mode5_origin_path: list = []                 # conveyor_path guardado para retomar
        self.mode5_done_splitter: bool = False            # splitter ya colocado
        self.last_conveyor_dir: Direction | None = None   # dirección del último conveyor colocado en modo 4

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

        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE and c.get_team() == c.get_team(b):
                self.spawn = c.get_position(b)
                break

        s = self.spawn
        layout = compute_layout_for_core(c, s)

        self.layout = layout['layout_positions']
        self.end_bridges_axionite = layout['axionite_entry']
        self.end_bridges_titanium = layout['entry_positions']

    def _in_bounds(self, pos: Position) -> bool:
        """Versión cacheada de _is_in_bounds — sin llamadas a la API."""
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

    @property
    def _active_ends(self) -> list:
        """Devuelve la lista de endpoints correcta según el tipo de camino activo."""
        if self.is_axionite_path:
            return self.end_bridges_axionite
        return self.end_bridges_titanium if self.end_bridges_titanium else self.layout

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

        if self.mode == 0:
            c.draw_indicator_dot(current, 255, 255, 255)
            self.buscar_material(c, current)
        if self.mode == 1:
            c.draw_indicator_dot(current, 24, 184, 69)
            self.place_bridge_ore(c)
            return
        elif self.mode == 2:
            c.draw_indicator_dot(current, 204, 16, 73)
            self.bridgeHome(c)
            return
        elif self.mode == 3:
            c.draw_indicator_dot(current, 237, 129, 26)
            self.revisar_camino_casa(c)
            return
        elif self.mode == 4:
            c.draw_indicator_dot(current, 26, 42, 219)
            self.place_conveyors(c)
            return
        elif self.mode == 5:
            c.draw_indicator_dot(current, 245, 39, 211)
            self.place_gunner_splitter(c)
            return

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
                          (env == Environment.ORE_AXIONITE and c.get_global_resources()[1] < 533) and len(self.titanium_harvesters) > 4)
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
                    transport_types = (
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.BRIDGE,
                        EntityType.SPLITTER,
                    )
                    entity = c.get_entity_type(building_id)
                    team = c.get_team() == c.get_team(building_id)
                    if entity == EntityType.HARVESTER:
                        flag = revisor_casillas_extractor(c, tile)
                        if env == Environment.ORE_TITANIUM and tile not in self.titanium_harvesters and flag:
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
                    elif entity in transport_types and team:
                        if tile in self.recolectores_set:
                                self.recolectores.remove(tile)
                                self.recolectores_set.discard(tile)
                        if tile in self.objetivos_set:
                            self.objetivos.remove(tile)
                            self.objetivos_set.discard(tile)
                            changed = True
                        continue
                    else:
                        if not ((c.is_tile_passable(tile) and c.get_position() != tile) or (entity == EntityType.BARRIER and not team)):
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
        self.oreCerca(c)
        target = None
        entityID = c.get_tile_building_id(current)
        if entityID is not None:
            tileTeam = c.get_team(entityID)
            if tileTeam != c.get_team() and c.get_entity_type(entityID) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]:
                if c.can_fire(current):
                    c.fire(current)
                return
            
        targets = self.objetivos
        targets.extend(self.recolectores)

        targets.sort(key=lambda p: current.distance_squared(p))

        if len(targets) > 0 and self.current_target is None:
            target = targets[0]
        else:
            target = None

        if target is not None:
            c.draw_indicator_line(current, target, 204, 39, 245)
            siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
            move_pos = current.add(siguiente_dir)
            c.draw_indicator_line(current, move_pos, 66, 245, 39)

            if c.is_in_vision(target):
                build_id = c.get_tile_building_id(target)
                if (build_id is not None and c.get_entity_type(build_id) != EntityType.HARVESTER 
                    and not self._clear_tile(c, target)):
                        return  # Aún no lo hemos roto

            if c.can_place_marker(target):
                c.place_marker(target, c.get_id())
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
                if (something is None or c.is_tile_passable(spot) or spot == c.get_position()) and something2 != Environment.WALL:
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
                return
            viable_places = extra_places_for_turrent

        current = c.get_position()
        viable_places.sort(key=lambda p: self.spawn.distance_squared(p))
        place = viable_places[0]
        c.draw_indicator_dot(place, 0, 0, 0)

        if place in active_ends:
            self.current_target = None
            self.mode = 0
            return

        if c.is_in_vision(place):
            if not self._clear_tile(c, place):
                return  # Aún no lo hemos roto

        if place == current:
            dir = self.navegador.moveTo(c, self.spawn, False)
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
                return

            # Para caminos de titanio: comprobar si conveyors son más baratas
            if not self.is_axionite_path:
                conv_path = _is_conv_better(c, place, target_end, self.layout)
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
                    self.mode = 4
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
            self.last_bridge_end = end
            self.last_bridge_built_pos = place
            self.bridge_destination = None
            self.bridge_origin = None

            # Para caminos de axionita: programar colocación del marker en turno siguiente
            if self.is_axionite_path:
                self.pending_axionite_marker = place

            if end in active_ends:
                self.current_target = None
                self.mode = 0
                self.last_bridge_end = None
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR)
                  and c.get_team() == c.get_team(c.get_tile_building_id(end))):
                self.mode = 3
            else:
                self.mode = 2

    # MODE 2

    def bridgeHome(self, c: Controller):
        current = c.get_position()
        bridge_end = self.last_bridge_end
        active_ends = self._active_ends

        if bridge_end is not None and bridge_end in active_ends:
            self.mode = 0
            self.last_bridge_end = None
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
                conv_path = _is_conv_better(c, bridge_end, target_end, self.layout)
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
                self.current_target = None
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR)
                  and c.get_team() == c.get_team(c.get_tile_building_id(end))):
                self.mode = 3
            else:
                self.mode = 2

    # MODE 3

    def revisar_camino_casa(self, c: Controller):
        current = c.get_position()
        active_ends = self._active_ends

        if self.check_pos is None:
            self.check_pos = self.last_bridge_end

        if self.check_pos is None: # No debería pasar?
            self.mode = 0
            self.current_target = None
            return

        if self.check_pos in active_ends:
            self.mode = 0
            self.check_pos = None
            self.last_bridge_end = None
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

        if building_id is None or entity not in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER):
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return

        if c.get_team(building_id) != c.get_team():
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
            self.mode = 0
            self.check_pos = None
            self.last_bridge_end = None
            self.current_target = None
            return

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

        # ── Comprobar si debemos colocar un gunner lateral (modo 5) ─────────────
        # Solo si no hay ningún GUNNER aliado visible en radio² 13
        gunner_nearby = any(
            c.get_entity_type(bid) == EntityType.GUNNER and c.get_team(bid) == c.get_team()
            for bid in c.get_nearby_buildings()
        )
        if not gunner_nearby and self.last_conveyor_dir is not None:
            result = self._find_gunner_spot(c, conv_pos, conv_dir)
            if result is not None:
                g_pos, g_dir, needs_splitter = result
                
                # Si no hay splitter, el conveyor en conv_pos sigue siendo necesario.
                # Construirlo ahora antes de saltar al modo 5.
                if not needs_splitter:
                    built = False
                    if c.can_build_armoured_conveyor(conv_pos, conv_dir):
                        c.build_armoured_conveyor(conv_pos, conv_dir)
                        built = True
                    elif c.can_build_conveyor(conv_pos, conv_dir):
                        c.build_conveyor(conv_pos, conv_dir)
                        built = True
                    if not built:
                        # No podemos construirlo aún, no saltar al modo 5 todavía
                        # El flujo normal del modo 4 lo reintentará el turno siguiente
                        pass  # ← caer al bloque de construcción normal abajo
                    else:
                        self.last_conveyor_dir = conv_dir
                        self.conveyor_path.pop(0)
                        self.last_bridge_end = conv_pos.add(conv_dir)
                        # Ahora sí saltar al modo 5 solo para el gunner
                        self.mode5_splitter_pos  = None
                        self.mode5_splitter_dir  = None
                        self.mode5_gunner_pos    = g_pos
                        self.mode5_gunner_dir    = g_dir
                        self.mode5_origin_path   = self.conveyor_path[:]  # path ya actualizado
                        self.conveyor_path       = []
                        self.mode5_done_splitter = True
                        self.mode = 5
                        return
                else:
                    self.mode5_splitter_pos  = conv_pos
                    self.mode5_splitter_dir  = self.last_conveyor_dir
                    self.mode5_gunner_pos    = g_pos
                    self.mode5_gunner_dir    = g_dir
                    self.mode5_origin_path   = self.conveyor_path[1:]
                    self.conveyor_path       = []
                    self.mode5_done_splitter = False
                    self.mode = 5
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
            self.last_conveyor_dir = conv_dir
            self.conveyor_path.pop(0)
            end = conv_pos.add(conv_dir)
            self.last_bridge_end = end
            self._check_conveyor_chain_end(c, end)

    def _check_conveyor_chain_end(self, c: Controller, end: Position):
        """
        Tras colocar (o saltar) un conveyor, comprueba si `end` ya es un nodo
        base o si la cadena está terminada, y actualiza el modo.
        """
        if end in self._active_ends:
            self.conveyor_path = []
            self.mode = 0
            self.last_bridge_end = None
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

    # MODE 5

    def place_gunner_splitter(self, c: Controller):
        """
        Coloca un splitter (en mode5_splitter_pos, dir mode5_splitter_dir) y
        un gunner (en mode5_gunner_pos, dir mode5_gunner_dir).
        Al terminar ambas construcciones, retoma el modo 4 con el path guardado.
        """
        current = c.get_position()

        # ── Paso 1: colocar el splitter ─────────────────────────────────────────
        if not self.mode5_done_splitter:
            sp = self.mode5_splitter_pos
            sd = self.mode5_splitter_dir

            c.draw_indicator_dot(sp, 255, 100, 0)

            # Acercarse si es necesario
            if current.distance_squared(sp) > 2:
                dir = self.navegador.moveTo(c, sp, four_dirs=False)
                next_pos = current.add(dir)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                self._try_move(c, dir)
                return

            # Limpiar si hay algo en la casilla
            if c.is_in_vision(sp):
                bid = c.get_tile_building_id(sp)
                if bid is not None:
                    et = c.get_entity_type(bid)
                    tm = c.get_team(bid)
                    # Si ya hay un splitter aliado con la misma dirección: saltar directamente
                    if et == EntityType.SPLITTER and tm == c.get_team() and c.get_direction(bid) == sd:
                        self.mode5_done_splitter = True
                    else:
                        if not self._clear_tile(c, sp):
                            return
                        
            if not self._clear_tile(c, sp):
                return

            if c.can_build_splitter(sp, sd):
                c.build_splitter(sp, sd)
                self.mode5_done_splitter = True
                # Actualizar last_bridge_end al output del splitter
                self.last_bridge_end = sp.add(sd)
            else:
                # No podemos aún (recursos, cooldown): esperar
                return

        # ── Paso 2: colocar el gunner ────────────────────────────────────────────
        gp = self.mode5_gunner_pos
        gd = self.mode5_gunner_dir

        c.draw_indicator_dot(gp, 255, 50, 200)  # Rosa

        # Limpiar si hay algo en la casilla
        if c.is_in_vision(gp):
            bid = c.get_tile_building_id(gp)
            if bid is not None:
                et = c.get_entity_type(bid)
                tm = c.get_team(bid)
                # Si ya hay un gunner aliado: listo
                if et == EntityType.GUNNER and tm == c.get_team():
                    self._finish_mode5(c)
                    return
                if not self._clear_tile(c, gp):
                    return
                
        # Acercarse si es necesario
        if current.distance_squared(gp) > 2:
            dir = self.navegador.moveTo(c, gp, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return
                
        # Si estamos encima de la casilla del gunner, apartarse primero
        if current == gp:
            for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
                adj = gp.add(d)
                if self._in_bounds(adj) and c.can_move(d):
                    c.move(d)
                    break
            return  # esperar al turno siguiente para construir

        if c.can_build_gunner(gp, gd):
            c.build_gunner(gp, gd)
            self._finish_mode5(c)
        # Si no podemos aún, esperamos al próximo turno

    def _finish_mode5(self, c: Controller):
        """Limpia el estado del modo 5 y retoma modo 4 con el path guardado."""
        self.conveyor_path = self.mode5_origin_path
        self.mode5_origin_path = []
        self.mode5_splitter_pos = None
        self.mode5_splitter_dir = None
        self.mode5_gunner_pos = None
        self.mode5_gunner_dir = None
        self.mode5_done_splitter = False
        self.last_conveyor_dir   = None
        self.mode = 4

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
            dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
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
            
    def _find_gunner_spot(
        self,
        c: Controller,
        conv_pos: Position,
        conv_dir: Direction,
    ) -> tuple["Position", "Direction", bool] | None:
        """
        Busca la mejor casilla adyacente cardinal de conv_pos para colocar un gunner.

        Scoring (mayor = mejor):
        +1000 si tiene un harvester aliado adyacente (N/S/E/O) → no necesita splitter
        -min_dist_sq_a_ore_sin_harvester  (más lejos de ores libres = mejor)

        Devuelve (spot, gunner_dir, needs_splitter) o None si no hay candidatos.
        needs_splitter=False cuando el spot tiene harvester adyacente.
        """
        cardinals = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

        future_path_positions: set[Position] = set()
        for fp, fd in self.conveyor_path:
            future_path_positions.add(fp)
            future_path_positions.add(fp.add(fd))

        transport_types = (
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
            EntityType.SPLITTER,
        )

        ore_envs = (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)

        # Recopilar todos los candidatos válidos con su score
        candidates: list[tuple[float, Position, Direction, bool]] = []

        for d in cardinals:
            spot = conv_pos.add(d)

            if not self._in_bounds(spot):
                continue
            if not c.is_in_vision(spot):
                continue
            if spot in self.layout:
                continue
            if spot in future_path_positions:
                continue
            if c.get_tile_env(spot) in (Environment.WALL, Environment.ORE_AXIONITE, Environment.ORE_TITANIUM):
                continue

            bid = c.get_tile_building_id(spot)
            if bid is not None:
                et   = c.get_entity_type(bid)
                team = c.get_team(bid)
                if et == EntityType.CORE:
                    continue
                if team == c.get_team() and et in transport_types:
                    continue
                if team == c.get_team():
                    if et not in (EntityType.ROAD, EntityType.BARRIER):
                        continue
                else:
                    if not c.is_tile_passable(spot):
                        continue

            # Dirección del gunner: conv_dir primero
            preferred_dirs = [conv_dir, conv_dir.opposite()]
            for pd in cardinals:
                if pd not in preferred_dirs:
                    preferred_dirs.append(pd)
            gunner_dir = preferred_dirs[0]

            # ── Scoring ─────────────────────────────────────────────────────────

            # ¿Tiene harvester aliado adyacente?
            has_adjacent_harvester = False
            for cd in cardinals:
                nb = spot.add(cd)
                if not self._in_bounds(nb):
                    continue
                nb_bid = c.get_tile_building_id(nb)
                if (nb_bid is not None
                        and c.get_entity_type(nb_bid) == EntityType.HARVESTER
                        and c.get_team(nb_bid) == c.get_team()):
                    has_adjacent_harvester = True
                    break

            if has_adjacent_harvester:
                score = 1000.0
                needs_splitter = False
            else:
                # Distancia mínima a ores sin harvester visibles
                min_ore_dist_sq = float("inf")
                for tile in c.get_nearby_tiles():
                    env = c.get_tile_env(tile)
                    if env not in ore_envs:
                        continue
                    # ¿Tiene harvester?
                    tile_bid = c.get_tile_building_id(tile)
                    if (tile_bid is not None
                            and c.get_entity_type(tile_bid) == EntityType.HARVESTER):
                        continue
                    dist_sq = spot.distance_squared(tile)
                    if dist_sq < min_ore_dist_sq:
                        min_ore_dist_sq = dist_sq

                score = -min_ore_dist_sq if min_ore_dist_sq != float("inf") else 0.0
                needs_splitter = True

            candidates.append((score, spot, gunner_dir, needs_splitter))

        if not candidates:
            return None

        # Mejor candidato: mayor score; desempate por orden de iteración (estable)
        candidates.sort(key=lambda x: -x[0])
        _, best_spot, best_dir, best_needs_splitter = candidates[0]
        return (best_spot, best_dir, best_needs_splitter)
    
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
        transport_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
        )
        for _ in range(depth):
            entity = c.get_entity_type(id)
            end = None
            if entity == EntityType.BRIDGE:
                end = c.get_bridge_target(id)
            elif entity in transport_types:
                end = c.get_position(id).add(c.get_direction(id))
            else:
                return False
            
            if end == me:
                return True
            elif c.is_in_vision(end) and self._in_bounds(end):
                id = c.get_tile_building_id(end)
                if c.get_entity_type(id) not in transport_types:
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
        transport_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
        )

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
                if nb_entity not in transport_types:
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
        transport_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
        )
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
            if nxt_et not in transport_types:
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

        transport_types = (
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
        )

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
                if candidate not in self._active_ends and candidate in self.layout:
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
                        if entity in transport_types:
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