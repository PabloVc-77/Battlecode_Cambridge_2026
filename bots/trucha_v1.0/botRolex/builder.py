from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bignav_a_mem as bugnav

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

def _is_conv_better(c: Controller, ini: Position, end: Position):
    """
    BFS desde ini hasta end. En cada paso el coste acumulado es:
        (i + 0.01 * i) * conveyor_cost  donde i = número de pasos
    Si encontramos camino antes de superar bridge_cost, devuelve
    lista de (pos, dir) para colocar las conveyors. Si no, None.
    """
    conveyor_cost = c.get_conveyor_cost()[0]

    from collections import deque
    queue = deque()
    queue.append((ini, []))
    visited = {ini}

    while queue:
        current, path = queue.popleft()

        i = len(path)
        coste_acumulado = (i + 0.01 * i) * conveyor_cost
        if coste_acumulado >= c.get_bridge_cost()[0]:
            return None  # ya es más caro que el puente, cortar

        if current == end:
            return path if len(path) > 0 else None

        for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
            neighbor = current.add(d)

            if neighbor in visited:
                continue
            if not _is_in_bounds(c, neighbor):
                continue
            if not c.is_in_vision(neighbor):
                continue

            env = c.get_tile_env(neighbor)
            if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE, Environment.WALL):
                continue

            building_id = c.get_tile_building_id(neighbor)
            if building_id is not None:
                if not c.is_tile_passable(neighbor):
                    continue

            visited.add(neighbor)
            queue.append((neighbor, path + [(current, d)]))

    return None  # no hay camino dentro del presupuesto


class Harvester:
    def __init__(self, c: Controller):
        self.objetivos = []
        self.objetivos_set = set()   # espejo de self.objetivos para lookups O(1)
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

        self.end_bridges = []
        self.mode = 0
            # mode 0: Find Ore (Blanco)
            # mode 1: Place bridge near Ore (Verde)
            # mode 2: go home (Rojo)
            # mode 3: revisar estructura (Naranja)
            # mode 4: conveyor mode (Azul Oscuro)
            # mode 5: torretas en primer harvester (Azul)
            # mode 6: colocar launcher junto a puente recién construido (Amarillo)
            # mode 7: colocar defensas alrededor del harvester
        self.last_bridge_end = None
        self.last_bridge_built_pos = None
        self.check_pos = None

        self.sentinel_placed = False

        # Variables de puentes
        self.bridge_origin = None         # casilla origen del puente pendiente de construir
        self.bridge_destination = None    # casilla destino del puente pendiente de construir

        self.recolectores = []
        self.turret_places = []

        self.first_bridge = None          # posición del primer puente construido (modo 5)
        self.is_first_builder = c.get_current_round() == 2  # Bug fix: round() es built-in de Python

        # Launcher mode vars
        self.pending_launcher_bridges = []  # cola de posiciones de puente que necesitan launcher
        self.mode_after_launcher = 2        # modo al que volver tras colocar el launcher

        # Cache de IDs de puentes verificados como conectados a la base en este turno
        self._connected_cache: dict[int, bool] = {}

        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_entity_type(b) == EntityType.CORE:
                self.spawn = c.get_position(b)
                break

        s = self.spawn
        viable_end_of_bridges = [s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST), s.add(Direction.NORTH).add(Direction.NORTH), s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST),
                                s.add(Direction.EAST).add(Direction.EAST).add(Direction.NORTH), s.add(Direction.EAST).add(Direction.EAST), s.add(Direction.EAST).add(Direction.EAST).add(Direction.SOUTH),
                                s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST), s.add(Direction.SOUTH).add(Direction.SOUTH), s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST),
                                s.add(Direction.WEST).add(Direction.WEST).add(Direction.NORTH), s.add(Direction.WEST).add(Direction.WEST), s.add(Direction.WEST).add(Direction.WEST).add(Direction.SOUTH)]

        for v in viable_end_of_bridges:
            if _is_in_bounds(c, v) and c.is_in_vision(v) and c.get_tile_env(v) != Environment.WALL:
                c.draw_indicator_dot(v, 245, 73, 39)
                self.end_bridges.append(v)

    def _in_bounds(self, pos: Position) -> bool:
        """Versión cacheada de _is_in_bounds — sin llamadas a la API."""
        return 0 <= pos.x < self.map_w and 0 <= pos.y < self.map_h

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
            c.draw_indicator_dot(current, 26, 42, 219)
            self.reforzar_harvester(c)
            return
        elif self.mode == 6:
            c.draw_indicator_dot(current, 255, 215, 0)
            self.colocar_launcher(c)
            return
        elif self.mode == 7:
            c.draw_indicator_dot(current, 100, 200, 200)
            self.colocar_defensas(c, self.current_target)
            return

        c.draw_indicator_dot(current, 255, 255, 255)

        self.oreCerca(c)
        target = None
        entityID = c.get_tile_building_id(current)
        if entityID is not None:
            tileTeam = c.get_team(entityID)
            if tileTeam != c.get_team() and c.get_entity_type(entityID) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]:
                if c.can_fire(current):
                    c.fire(current)
                return

        if len(self.objetivos) > 0:
            target = self.objetivos[0]
        elif len(self.recolectores) > 0:
            target = self.recolectores[0]
        else:
            target = None

        if target is not None:
            c.draw_indicator_line(current, target, 204, 39, 245)
            siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
            move_pos = current.add(siguiente_dir)
            c.draw_indicator_line(current, move_pos, 66, 245, 39)

            if c.is_in_vision(target):
                build_id = c.get_tile_building_id(target)
                if (build_id is not None and c.get_entity_type(build_id) != EntityType.HARVESTER) and not self._clear_tile(c, target):
                    return  # Aún no lo hemos roto

            if c.can_build_harvester(target):
                c.build_harvester(target)
                self.current_target = target
                if target in self.objetivos_set:
                    self.objetivos.remove(target)
                    self.objetivos_set.discard(target)
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

        if len(viable_places) == 0:
            self.current_target = None
            self.mode = 0
            return

        current = c.get_position()
        viable_places.sort(key=lambda p: self.spawn.distance_squared(p))
        place = viable_places[0]
        c.draw_indicator_dot(place, 0, 0, 0)

        if place in self.end_bridges:
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
            if target_end is None:
                self.mode = 0
                return

            # Comprobar si conveyors son más baratas que un puente
            conv_path = _is_conv_better(c, place, target_end)
            self.conveyor_path = conv_path
            if conv_path is not None and len(conv_path) > 0:
                conv_pos, conv_dir = conv_path[0]
                if c.can_build_armoured_conveyor(conv_pos, conv_dir):
                    c.build_armoured_conveyor(conv_pos, conv_dir)
                elif c.can_build_conveyor(conv_pos, conv_dir):
                    c.build_conveyor(conv_pos, conv_dir)
                    self.conveyor_path.pop(0)
                    self.last_bridge_end = conv_pos.add(conv_dir)
                self.mode_after_conv = 1
                self.mode = 4
                return

            c.draw_indicator_dot(target_end, 255, 255, 255)

            if c.can_build_bridge(place, target_end):
                end = target_end
            else:
                end = self._find_bridge_step(place, target_end, c, nearby_builds)
                if end is None:
                    self.mode = 0
                    return

        c.draw_indicator_dot(end, 255, 255, 255)

        # Quitar barrier propia en place si la hay
        building_id_place = c.get_tile_building_id(place)
        if (building_id_place is not None
                and c.get_entity_type(building_id_place) == EntityType.BARRIER
                and c.get_team(building_id_place) == c.get_team()):
            if c.can_destroy(place):
                c.destroy(place)
            return

        if c.can_build_bridge(place, end):
            c.build_bridge(place, end)
            self.last_bridge_end = end
            self.pending_launcher_bridges.append(place)
            self.last_bridge_built_pos = place
            self.bridge_destination = None
            self.bridge_origin = None

            if end in self.end_bridges:
                self.mode_after_launcher = 0
                self.last_bridge_end = None
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end)) == EntityType.BRIDGE):
                self.mode_after_launcher = 3
            else:
                self.mode_after_launcher = 2

            self.mode = 7

    # MODE 2

    def bridgeHome(self, c: Controller):
        current = c.get_position()
        bridge_end = self.last_bridge_end

        if bridge_end is not None and bridge_end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None
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

            c.draw_indicator_dot(target_end, 255, 255, 0)

            # Comprobar si conveyors son más baratas que un puente
            conv_path = _is_conv_better(c, bridge_end, target_end)
            self.conveyor_path = conv_path
            if conv_path is not None and len(conv_path) > 0:
                conv_pos, conv_dir = conv_path[0]
                if c.can_build_conveyor(conv_pos, conv_dir):
                    c.build_conveyor(conv_pos, conv_dir)
                    self.conveyor_path.pop(0)
                    self.last_bridge_end = conv_pos.add(conv_dir)
                self.mode_after_conv = 2
                self.mode = 4
                return

            if c.can_build_bridge(bridge_end, target_end):
                end = target_end
            else:
                end = self._find_bridge_step(bridge_end, target_end, c, nearby_builds)
                if end is None:
                    dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    self._try_move(c, dir)
                    return

        if c.is_in_vision(bridge_end):
            if not self._clear_tile(c, bridge_end):
                return  # Aún no lo hemos roto

        # Quitar barrier propia en bridge_end si la hay
        building_id_be = c.get_tile_building_id(bridge_end)
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
            self.pending_launcher_bridges.append(bridge_end)
            self.bridge_destination = None
            self.bridge_origin = None

            if end in self.end_bridges:
                self.mode_after_launcher = 0
                self.last_bridge_end = None
            elif (c.is_in_vision(end)
                  and c.get_tile_building_id(end) is not None
                  and c.get_entity_type(c.get_tile_building_id(end)) == EntityType.BRIDGE):
                self.mode_after_launcher = 3
            else:
                self.mode_after_launcher = 2

            self.mode = 6

    def oreCerca(self, c: Controller):
        lista = c.get_nearby_tiles()
        changed = False
        ronda = c.get_current_round()
        for tile in lista:
            env = c.get_tile_env(tile)  # llamada única por tile
            es_mineral = (env == Environment.ORE_TITANIUM or
                          (env == Environment.ORE_AXIONITE and ronda >= 100))

            if es_mineral:
                building_id = c.get_tile_building_id(tile)

                if building_id is not None:
                    if c.get_entity_type(building_id) == EntityType.HARVESTER:
                        if not revisor_casillas_extractor(c, tile):
                            if tile not in self.recolectores_set:
                                self.recolectores.append(tile)
                                self.recolectores_set.add(tile)
                        else:
                            if tile in self.recolectores_set:
                                self.recolectores.remove(tile)
                                self.recolectores_set.discard(tile)
                        continue
                    else:
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

    # MODE 3

    def revisar_camino_casa(self, c: Controller):
        current = c.get_position()

        if self.check_pos is None:
            self.check_pos = self.last_bridge_end

        if self.check_pos is None:
            self.mode = 0
            return

        if self.check_pos in self.end_bridges:
            self.mode = 0
            self.check_pos = None
            self.last_bridge_end = None
            return

        c.draw_indicator_dot(self.check_pos, 255, 128, 0)

        if not c.is_in_vision(self.check_pos):
            dir = self.navegador.moveTo(c, self.check_pos, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return

        building_id = c.get_tile_building_id(self.check_pos)

        if building_id is None or c.get_entity_type(building_id) != EntityType.BRIDGE:
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return

        if c.get_team(building_id) != c.get_team():
            self.last_bridge_end = self.check_pos
            self.check_pos = None
            self.mode = 2
            return

        next_check = c.get_bridge_target(building_id)

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
        if not self.conveyor_path:
            self.mode = self.mode_after_conv
            return

        current = c.get_position()
        conv_pos, conv_dir = self.conveyor_path[0]

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
            self.conveyor_path.pop(0)
            end = conv_pos.add(conv_dir)
            self.last_bridge_end = end
            self._check_conveyor_chain_end(c, end)

    def _check_conveyor_chain_end(self, c: Controller, end: Position):
        """
        Tras colocar (o saltar) un conveyor, comprueba si `end` ya es un nodo
        base o si la cadena está terminada, y actualiza el modo.
        """
        if end in self.end_bridges:
            self.conveyor_path = []
            self.mode = 0
            self.last_bridge_end = None
            return

        if not self.conveyor_path:
            if c.is_in_vision(end):
                end_bid = c.get_tile_building_id(end)
                if (end_bid is not None
                        and c.get_team(end_bid) == c.get_team()
                        and c.get_entity_type(end_bid) in (
                            EntityType.BRIDGE,
                            EntityType.CONVEYOR,
                            EntityType.ARMOURED_CONVEYOR)):
                    self.mode = 3
                    return
            self.mode = self.mode_after_conv

    # MODE 5

    def reforzar_harvester(self, c: Controller):
        self.turret_places.sort(key=lambda p: self.spawn.distance_squared(p))

        if len(self.turret_places) == 0:
            self.mode = 2
            end = None
            if self.first_bridge is not None and c.is_in_vision(self.first_bridge):
                bid = c.get_tile_building_id(self.first_bridge)
                if bid is not None:
                    end = c.get_bridge_target(bid)

            if end is not None and end in self.end_bridges:
                self.mode = 0
                self.last_bridge_end = None
            return

        place_to_build = None
        t_place = self.turret_places[0]
        t_id = c.get_tile_building_id(t_place)
        dir = t_place.direction_to(self.first_bridge) if self.first_bridge is not None else Direction.NORTH

        if t_id is not None and c.get_entity_type(t_id) != EntityType.SENTINEL:
            if c.can_destroy(t_place):
                c.destroy(t_place)
            if c.can_fire(t_place):
                c.fire(t_place)

        if c.can_build_sentinel(t_place, dir):
            c.build_sentinel(t_place, dir)
        elif place_to_build is None or (t_id is not None and c.get_entity_type(t_id) != EntityType.SENTINEL):
            place_to_build = t_place

        if place_to_build is None:
            self.mode = 2
            end = None
            if self.first_bridge is not None and c.is_in_vision(self.first_bridge):
                bid = c.get_tile_building_id(self.first_bridge)
                if bid is not None:
                    end = c.get_bridge_target(bid)

            if end is not None and end in self.end_bridges:
                self.mode = 0
                self.last_bridge_end = None
            return

        current = c.get_position()
        dist = current.distance_squared(place_to_build)
        place_id = c.get_tile_building_id(place_to_build)
        if dist > 2:
            direc = self.navegador.moveTo(c, place_to_build, False)
            move_pos = current.add(direc)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if current.add(direc).distance_squared(place_to_build) != 0 or (place_id is not None and c.get_team(place_id) != c.get_team()):
                self._try_move(c, direc)
        elif dist == 0 and (place_id is None or c.get_team(place_id) == c.get_team()):
            direc = self.navegador.moveTo(c, self.spawn, False)
            move_pos = current.add(direc)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            self._try_move(c, direc)

    # MODE 6

    def _get_launcher_spot(self, c: Controller, bridge_pos: Position) -> Position | None:
        """
        Busca una casilla adyacente (dist² <= 2) a bridge_pos donde colocar un launcher.
        Devuelve None si ya hay un launcher aliado cerca (no hace falta construir otro).
        Prefiere la casilla más cercana al spawn.
        """
        candidates = []
        for ddx in range(-1, 2):
            for ddy in range(-1, 2):
                if ddx == 0 and ddy == 0:
                    continue
                spot = Position(bridge_pos.x + ddx, bridge_pos.y + ddy)
                if not self._in_bounds(spot):
                    continue
                if not c.is_in_vision(spot):
                    continue
                if spot in self.end_bridges:
                    continue
                env = c.get_tile_env(spot)
                if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                    continue
                if self.last_bridge_end is not None and self.last_bridge_end == spot:
                    continue
                building_id = c.get_tile_building_id(spot)
                if building_id is not None:
                    # Si ya hay un launcher aliado, no hace falta construir
                    if c.get_entity_type(building_id) == EntityType.LAUNCHER and c.get_team(building_id) == c.get_team():
                        return None
                    if not c.is_tile_passable(spot):
                        continue
                    if c.get_entity_type(building_id) in (EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE) and c.get_team() == c.get_team(building_id):
                        continue
                    if c.get_entity_type(building_id) == EntityType.CORE:
                        continue
                candidates.append(spot)

        if not candidates:
            return None

        candidates.sort(key=lambda p: self.spawn.distance_squared(p))
        return candidates[0]

    def colocar_launcher(self, c: Controller):
        """Modo 6: coloca un launcher junto al puente pendiente, luego vuelve al modo anterior."""
        if not self.pending_launcher_bridges:
            self.mode = self.mode_after_launcher
            return

        bridge_pos = self.pending_launcher_bridges[0]
        current = c.get_position()

        spot = self._get_launcher_spot(c, bridge_pos)

        if spot is None:
            # Ya tiene launcher o no hay hueco — pasar al siguiente puente pendiente
            self.pending_launcher_bridges.pop(0)
            if not self.pending_launcher_bridges:
                self.mode = self.mode_after_launcher
            return

        # Acercarnos si hace falta
        if current.distance_squared(spot) > 2:
            dir = self.navegador.moveTo(c, spot, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            self._try_move(c, dir)
            return

        # Limpiar si hay algo en el spot
        if not self._clear_tile(c, spot):
            return

        if c.can_build_launcher(spot):
            c.build_launcher(spot)
            self.pending_launcher_bridges.pop(0)
            if not self.pending_launcher_bridges:
                self.mode = self.mode_after_launcher

    # MODE 7

    def colocar_defensas(self, c: Controller, harvester_pos: Position):
        if harvester_pos is None:
            self.mode = 6
            return

        candidates = [
            harvester_pos.add(Direction.NORTH),
            harvester_pos.add(Direction.EAST),
            harvester_pos.add(Direction.SOUTH),
            harvester_pos.add(Direction.WEST),
        ]

        # Determinar cuál casilla es la del puente (la más cercana a last_bridge_built_pos)
        #sentinel_spot = None
        #if self.last_bridge_built_pos is not None and not self.sentinel_placed:
        #    closest = min(
        #        [p for p in candidates if self._in_bounds(p) and self.last_bridge_built_pos != p and c.is_in_vision(p) and (c.is_tile_passable(p) or c.is_tile_empty(p))],
        #        key=lambda p: p.distance_squared(self.last_bridge_built_pos),
        #        default=None
        #    )
        #    sentinel_spot = closest

        for objetivo in candidates:
            if not self._in_bounds(objetivo):
                continue

            # Acercarnos si no está en visión
            if not c.is_in_vision(objetivo):
                dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                self._try_move(c, dir)
                return

            if c.get_tile_env(objetivo) in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
                continue

            building_id = c.get_tile_building_id(objetivo)
            edificio_deseado = EntityType.BARRIER

            if building_id is not None:
                entity = c.get_entity_type(building_id)
                team = c.get_team(building_id)

                # Ya tiene lo que queremos: casilla resuelta
                if entity == edificio_deseado and team == c.get_team():
                    continue

                if entity in (EntityType.BRIDGE, EntityType.SENTINEL) and team == c.get_team():
                    continue

                # Estructura enemiga: intentar destruirla
                if not self._clear_tile(c, objetivo):
                    return

            # Casilla vacía o recién liberada: construir lo que toca
            resultado = self.construir(c, objetivo, edificio_deseado)
            if not resultado:
                return

        # Todas las casillas resueltas
        self.sentinel_placed = False
        self.mode = 6

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

    def _is_connected_to_base(self, c: Controller, bridge_id) -> bool:
        """
        Sigue la cadena de puentes desde bridge_id hasta su endpoint final.
        Devuelve True si ese endpoint está en end_bridges (conectado a la base).
        Usa _connected_cache (reiniciado cada turno) para no recorrer la misma cadena varias veces.
        """
        if bridge_id in self._connected_cache:
            return self._connected_cache[bridge_id]

        visited = set()
        current_id = bridge_id
        chain_ids = []

        while current_id is not None:
            if current_id in self._connected_cache:
                result = self._connected_cache[current_id]
                for cid in chain_ids:
                    self._connected_cache[cid] = result
                return result

            pos = c.get_position(current_id)
            if pos in visited:
                break  # Ciclo inesperado; evitar bucle infinito
            visited.add(pos)
            chain_ids.append(current_id)

            endpoint = c.get_bridge_target(current_id)
            if endpoint is None:
                break

            if endpoint in self.end_bridges:
                for cid in chain_ids:
                    self._connected_cache[cid] = True
                return True

            if not c.is_in_vision(endpoint):
                break  # No podemos verificar más allá

            next_id = c.get_tile_building_id(endpoint)
            if next_id is None or c.get_entity_type(next_id) != EntityType.BRIDGE:
                break  # La cadena termina aquí y no llegó a end_bridges

            current_id = next_id

        for cid in chain_ids:
            self._connected_cache[cid] = False
        return False

    def _find_best_bridge_end(self, place: Position, c: Controller, builds: list) -> Position | None:
        """
        Primero intenta conectar a un puente aliado cercano que ya esté conectado
        a la base. Si no encuentra ninguno, usa end_bridges directamente.
        Recibe `builds` (resultado de get_nearby_buildings) para no repetir la llamada.
        """
        # ── 1. Buscar puentes aliados cercanos conectados a la base ──────────────
        chain_candidates = []

        for b in builds:
            if c.get_team(b) != c.get_team():
                continue
            if c.get_entity_type(b) != EntityType.BRIDGE:
                continue

            b_pos = c.get_position(b)
            if place.distance_squared(b_pos) > 9:
                continue
            if b_pos == self.last_bridge_end:
                continue

            if self._is_connected_to_base(c, b):
                chain_candidates.append(b_pos)

        # ── 2. Si hay candidatos de cadena, usar el más cercano a place ──────────
        if chain_candidates:
            chain_candidates.sort(key=lambda p: place.distance_squared(p))
            return chain_candidates[0]

        # ── 3. Comportamiento original: apuntar a end_bridges ────────────────────
        candidates = sorted(self.end_bridges, key=lambda p: place.distance_squared(p))
        for end in candidates:
            if end == self.last_bridge_end:
                continue
            if self._in_bounds(end):
                return end

        return None

    def _find_bridge_step(self, place: Position, target: Position, c: Controller, builds: list) -> Position | None:
        """Solo se ejecuta si el puente directo no alcanza. Bucle 7x7 + puentes aliados visibles."""
        dx = target.x - place.x
        dy = target.y - place.y
        dist = math.sqrt(dx * dx + dy * dy)
        ux, uy = dx / dist, dy / dist

        best: Position | None = None
        best_score: tuple | None = None  # (-remaining_sq, dot) — mayor = mejor

        for ddx in range(-3, 4):
            for ddy in range(-3, 4):
                d_sq = ddx * ddx + ddy * ddy
                if d_sq == 0 or d_sq > 9:
                    continue
                dot = ddx * ux + ddy * uy
                if dot <= 0:
                    continue

                candidate = Position(place.x + ddx, place.y + ddy)
                if not self._in_bounds(candidate) or not c.is_in_vision(candidate):
                    continue

                env = c.get_tile_env(candidate)
                if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE, Environment.WALL):
                    continue

                building_id = c.get_tile_building_id(candidate)
                if building_id is not None:
                    entity_type = c.get_entity_type(building_id)
                    if c.get_team(building_id) != c.get_team() and not c.is_tile_passable(candidate):
                        continue
                    if entity_type not in (EntityType.ROAD, EntityType.CONVEYOR,
                                        EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER,
                                        EntityType.FOUNDRY):
                        continue

                remaining_sq = candidate.distance_squared(target)
                score = (-remaining_sq, dot)
                if best_score is None or score > best_score:
                    best_score = score
                    best = candidate

        # Puentes aliados visibles como destino intermedio
        for b in builds:
            if c.get_team(b) != c.get_team():
                continue
            if c.get_entity_type(b) != EntityType.BRIDGE:
                continue

            b_pos = c.get_position(b)
            if place.distance_squared(b_pos) > 9:
                continue

            end_point = c.get_bridge_target(b)
            end_id = c.get_tile_building_id(end_point) if c.is_in_vision(end_point) else None
            while end_id is not None and c.get_entity_type(end_id) == EntityType.BRIDGE:
                end_point = c.get_bridge_target(end_id)
                end_id = c.get_tile_building_id(end_point) if c.is_in_vision(end_point) else None

            remaining_sq = end_point.distance_squared(target)
            dot = (b_pos.x - place.x) * ux + (b_pos.y - place.y) * uy
            score = (-remaining_sq, dot)
            if best_score is None or score > best_score:
                best_score = score
                best = b_pos

        return best