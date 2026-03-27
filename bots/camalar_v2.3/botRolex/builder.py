from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bignav_opus as bugnav

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()

    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

def _find_viable_bridge_end(end_of_bridges, place: Position, candidates: list, c: Controller) -> Position | None:
    best_direct = None      # conecta directo a un end_bridge
    best_chained = None     # encadena con otro puente

    for target in candidates:
        end = _get_end_of_bridge(end_of_bridges, place, target, c)
        if end is None:
            continue
        if end in end_of_bridges:
            return end  # no hay nada mejor, salir ya
        if best_chained is None:
            best_chained = end

    return best_chained  # solo si no hubo ningún directo

def _get_end_of_bridge(end_bridges, place: Position, target: Position, c: Controller) -> Position | None:
    dx = target.x - place.x
    dy = target.y - place.y
    dist_sq = dx * dx + dy * dy

    if dist_sq == 0:
        return None

    dist = math.sqrt(dist_sq)
    ux = dx / dist
    uy = dy / dist

    best = None
    best_score = None  # (dist_to_target_sq negado, d_sq, dot) — menor dist_to_target primero

    for ddx in range(-3, 4):
        for ddy in range(-3, 4):
            d_sq = ddx * ddx + ddy * ddy
            if d_sq == 0 or d_sq > 9:
                continue

            candidate = Position(place.x + ddx, place.y + ddy)

            if not _is_in_bounds(c, candidate):
                continue

            dot = ddx * ux + ddy * uy
            if dot <= 0:
                continue
            
            # Si no está en visión, no lo aceptamos (no sabemos qué hay)
            if c.is_in_vision(candidate):
                env = c.get_tile_env(candidate)
                if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE, Environment.WALL):
                    continue
                
                building_id = c.get_tile_building_id(candidate)
                if building_id is not None:
                    if c.get_team(building_id) != c.get_team() and not c.is_tile_passable(candidate):
                        continue
                    if c.get_entity_type(building_id) not in (EntityType.ROAD, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER, EntityType.FOUNDRY):
                        continue
            else:
                continue

            # Distancia restante al target desde este candidato
            remaining_sq = candidate.distance_squared(target)

            # Score: minimizar distancia restante, luego maximizar avance y alineación
            score = (-remaining_sq, d_sq, dot)
            if best_score is None or score > best_score:
                best_score = score
                best = candidate

    builds = c.get_nearby_buildings()
    bridges = list(filter(lambda b: c.get_team(b) == c.get_team() and c.get_entity_type(b) == EntityType.BRIDGE, builds))

    if best is not None:
        best_score = best.distance_squared(target)
    else:
        best_score = -1

    if best is not None and best in end_bridges:
        return best

    for b in bridges:
        end_point = c.get_bridge_target(b)
        remaining_sq = end_point.distance_squared(target)
        end = c.get_position(b)
        c.draw_indicator_dot(end, 245, 73, 39)
        c.draw_indicator_line(end, end_point, 245, 73, 39)
        if best_score >= remaining_sq and place.distance_squared(end) <= 9:
            best_score = remaining_sq
            best = end

    return best

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


class Harvester:
    def __init__(self, c: Controller):
        self.objetivos = []

        # Builder Vars
        self.navegador = bugnav.BugNav()
        self.spawn = None
        self.conveyor_mode = False
        self.current_target = None

        self.end_bridges = []
        self.mode = 0
            # mode 0: Find Ore (Blanco)
            # mode 1: Place bridge near Ore (Verde)
            # mode 2: go home (Rojo)
            # mode 3: revisar estructura (Naranja)
            # mode 5: torretas en primer harvester (Azul)
            # mode 6: colocar launcher junto a puente recién construido (Amarillo)
        self.last_bridge_end = None
        self.check_pos = None

        self.recolectores = []
        self.turret_places = []

        self.is_first_builder = round == 2

        # Launcher mode vars
        self.pending_launcher_bridges = []  # cola de posiciones de puente que necesitan launcher
        self.mode_after_launcher = 2        # modo al que volver tras colocar el launcher

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
                                #s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST).add(Direction.EAST), s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST).add(Direction.WEST),
                                #s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST).add(Direction.EAST), s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST).add(Direction.WEST)]

        for v in viable_end_of_bridges:
            if _is_in_bounds(c, v):
                c.draw_indicator_dot(v, 245, 73, 39)
                self.end_bridges.append(v)

    def run(self, c: Controller):
        current = c.get_position()

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
        elif self.mode == 5:
            c.draw_indicator_dot(current, 26, 42, 219)
            self.reforzar_harvester(c)
            return
        elif self.mode == 6:
            c.draw_indicator_dot(current, 255, 215, 0)
            self.colocar_launcher(c)
            return

        c.draw_indicator_dot(current, 255, 255, 255)

        self.oreCerca(c)
        target = None
        entityID = c.get_tile_building_id(current)
        tileTeam = c.get_team(entityID)
        if tileTeam is not None and tileTeam != c.get_team() and c.get_entity_type(entityID) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE]:
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
                if target in self.objetivos:
                    self.objetivos.remove(target)
                self.mode = 1
            elif current.distance_squared(target) > 2:
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)
                if c.can_move(siguiente_dir) and current.add(siguiente_dir).distance_squared(target) != 0:
                    c.move(siguiente_dir)
            else:
                # Estamos al lado del target pero no podemos construir harvester
                b_id = c.get_tile_building_id(target)
                if b_id is not None and c.get_entity_type(b_id) == EntityType.HARVESTER and not revisor_casillas_extractor(c, c.get_position(b_id)):
                    self.current_target = target
                    if target in self.objetivos:
                        self.objetivos.remove(target)
                    if target in self.recolectores:
                        self.recolectores.remove(target)
                    self.mode = 1
                    return

                if target in self.objetivos:
                    self.objetivos.remove(target)
                self.current_target = None
        else:
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)

    def place_bridge_ore(self, c: Controller):
        places = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
        viable_places = []
        extra_places_for_turrent = []
        for d in places:
            spot = self.current_target.add(d)
            if _is_in_bounds(c, spot) and c.is_in_vision(spot):
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
            if c.can_move(dir):
                c.move(dir)

        if current.distance_squared(place) > 2:
            dir = self.navegador.moveTo(c, place, False)
            move_pos = current.add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(dir):
                c.move(dir)

        self.end_bridges.sort(key=lambda p: place.distance_squared(p))
        end = _find_viable_bridge_end(self.end_bridges, place, self.end_bridges, c)
        if end is None:
            self.mode = 0
            return

        c.draw_indicator_dot(end, 255, 255, 255)
        if c.can_build_bridge(place, end):
            c.build_bridge(place, end)
            self.last_bridge_end = end

            # Encolar launcher para este puente
            self.pending_launcher_bridges.append(place)

            # Determinar modo siguiente (que será el que recupere el launcher al terminar)
            if end in self.end_bridges:
                self.mode_after_launcher = 0
                self.last_bridge_end = None
            elif c.get_entity_type(c.get_tile_building_id(end)) == EntityType.BRIDGE:
                self.mode_after_launcher = 3
            else:
                self.mode_after_launcher = 2

            self.mode = 6

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
            if c.can_move(dir):
                c.move(dir)
            return

        # En anchor — colocar siguiente puente
        self.end_bridges.sort(key=lambda p: bridge_end.distance_squared(p))
        end = _find_viable_bridge_end(self.end_bridges, bridge_end, self.end_bridges, c)

        if end is None:
            dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        c.draw_indicator_dot(end, 255, 255, 0)

        if c.is_in_vision(bridge_end):
            if not self._clear_tile(c, bridge_end):
                return  # Aún no lo hemos roto

        if c.can_build_bridge(bridge_end, end):
            c.build_bridge(bridge_end, end)
            self.last_bridge_end = end

            # Encolar launcher para este puente
            self.pending_launcher_bridges.append(bridge_end)

            # Determinar modo siguiente
            if end in self.end_bridges:
                self.mode_after_launcher = 0
                self.last_bridge_end = None
            elif c.get_entity_type(c.get_tile_building_id(end)) == EntityType.BRIDGE:
                self.mode_after_launcher = 3
            else:
                self.mode_after_launcher = 2

            self.mode = 6

    def oreCerca(self, c: Controller):
        lista = c.get_nearby_tiles()
        for tile in lista:
            if c.get_tile_env(tile) == Environment.ORE_TITANIUM or (c.get_tile_env(tile) == Environment.ORE_AXIONITE and c.get_current_round() >= 100):
                building_id = c.get_tile_building_id(tile)

                if building_id is not None:
                    if c.get_entity_type(building_id) == EntityType.HARVESTER:
                        if not revisor_casillas_extractor(c, tile):
                            if tile not in self.recolectores:
                                self.recolectores.append(tile)
                        elif tile in self.recolectores:
                            self.recolectores.remove(tile)
                        continue

                if tile not in self.objetivos:
                    self.objetivos.append(tile)

            elif tile in self.objetivos:
                self.objetivos.remove(tile)

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
            if c.can_move(dir):
                c.move(dir)
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

    # MODE 5

    def reforzar_harvester(self, c: Controller):
        self.turret_places.sort(key=lambda p: self.spawn.distance_squared(p))

        if len(self.turret_places) == 0:
            self.mode = 2
            end = None
            if c.is_in_vision(self.first_bridge):
                end = c.get_bridge_target(c.get_tile_building_id(self.first_bridge))

            if end is not None and end in self.end_bridges:
                self.mode = 0
                self.last_bridge_end = None
            return

        place_to_build = None
        t_place = self.turret_places[0]
        t_id = c.get_tile_building_id(t_place)
        dir = t_place.direction_to(self.first_bridge)

        if t_id is not None and c.get_entity_type(t_id) != EntityType.SENTINEL:
            if c.can_destroy(t_place):
                c.destroy(t_place)
            if c.can_fire(t_place):
                c.fire(t_place)

        if c.can_build_sentinel(t_place, dir):
            c.build_sentinel(t_place, dir)
        elif place_to_build is None or c.get_entity_type(t_id) != EntityType.SENTINEL:
            place_to_build = t_place

        if place_to_build is None:
            self.mode = 2
            end = None
            if c.is_in_vision(self.first_bridge):
                end = c.get_bridge_target(c.get_tile_building_id(self.first_bridge))

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
            if c.can_move(direc) and (current.add(direc).distance_squared(place_to_build) != 0 or (place_id is not None and c.get_team(place_id) != c.get_team())):
                c.move(direc)
        elif dist == 0 and (place_id is None or c.get_team(place_id) == c.get_team()):
            direc = self.navegador.moveTo(c, self.spawn, False)
            move_pos = current.add(direc)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(direc):
                c.move(direc)

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
                if not _is_in_bounds(c, spot):
                    continue
                if not c.is_in_vision(spot):
                    continue
                env = c.get_tile_env(spot)
                if env in (Environment.WALL, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
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
            if c.can_move(dir):
                c.move(dir)
            return

        # Limpiar si hay algo en el spot
        if not self._clear_tile(c, spot):
            return

        if c.can_build_launcher(spot):
            c.build_launcher(spot)
            self.pending_launcher_bridges.pop(0)
            if not self.pending_launcher_bridges:
                self.mode = self.mode_after_launcher

    # UTILITY

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        """
        Intenta eliminar lo que haya en `target`.
        - Aliado: c.destroy() si estamos a distancia² <= 2.
        - Enemigo: c.fire() solo si estamos encima (distancia² == 0).

        Devuelve True si el tile ya está despejado (no hay nada),
        False si aún queda algo (o no podemos actuar todavía).
        En caso de que necesitemos acercarnos, hace el movimiento.
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
            if c.can_move(dir):
                c.move(dir)
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
                    if c.can_move(dir):
                        c.move(dir)
                return False