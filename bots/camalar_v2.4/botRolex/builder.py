from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bignav_opus as bugnav

def _is_in_bounds(c: Controller, pos: Position) -> bool:
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
            # mode 7: colocar defensas alrededor del harvester
            # mode 8: poner barrier adelantada en casilla destino del puente (Morado)
        self.last_bridge_end = None
        self.last_bridge_built_pos = None
        self.check_pos = None

        self.sentinel_placed = False

        #Variables de puentes
        self.pending_barrier_pos = None   # casilla donde hay que poner la barrier adelantada
        self.mode_after_barrier = 1       # modo al que volver tras completar el modo 8
        self.bridge_origin = None         # casilla origen del puente pendiente de construir
        self.bridge_destination = None    # casilla destino del puente pendiente de construir

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
            if _is_in_bounds(c, v) and c.is_in_vision(v) and c.get_tile_env(v) != Environment.WALL:
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
        elif self.mode == 7:
            c.draw_indicator_dot(current, 100, 200, 200)
            self.colocar_defensas(c, self.current_target)
            return
        elif self.mode == 8:
            c.draw_indicator_dot(current, 180, 0, 180)  # morado
            self.poner_barrier_adelantada(c)
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

            elif current == target:
                for d in Direction:
                    if d == Direction.CENTRE:
                        continue
                    adj = target.add(d)
                    if _is_in_bounds(c, adj) and c.can_move(d):
                        c.move(d)
                        break

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
            return

        if current.distance_squared(place) > 2:
            dir = self.navegador.moveTo(c, place, False)
            move_pos = current.add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        # --- Selección del destino (barata, sin llamadas al motor) ---
        target_end = self._find_best_bridge_end(place, c)
        if target_end is None:
            self.mode = 0
            return

        c.draw_indicator_dot(target_end, 255, 255, 255)

        # --- Solo si el puente directo no alcanza, buscar paso intermedio ---
        if c.can_build_bridge(place, target_end):
            end = target_end
        else:
            end = self._find_bridge_step(place, target_end, c)
            if end is None:
                self.mode = 0
                return

        c.draw_indicator_dot(end, 255, 255, 255)

        # Si ya tenemos un destino fijo guardado (volvemos del modo 8), usarlo
        if self.bridge_destination is not None:
            end = self.bridge_destination

        # Quitar barrier propia en place si la hay (la pusimos nosotros en un tick anterior)
        building_id_place = c.get_tile_building_id(place)
        if (building_id_place is not None
                and c.get_entity_type(building_id_place) == EntityType.BARRIER
                and c.get_team(building_id_place) == c.get_team()):
            if c.can_destroy(place):
                c.destroy(place)
            return  # Turno siguiente: casilla libre, construiremos el puente

        # Primera vez: activar modo 8 para poner barrier en end (si procede)
        if self.bridge_destination is None:
            skip_barrier = (
                end in self.end_bridges
                or (c.is_in_vision(end) and c.get_tile_building_id(end) is not None
                    and c.get_entity_type(c.get_tile_building_id(end)) == EntityType.BRIDGE
                    and c.get_team(c.get_tile_building_id(end)) == c.get_team())
            )
            if not skip_barrier:
                self.pending_barrier_pos = end
                self.bridge_destination = end  # fijar destino
                self.bridge_origin = place
                self.mode_after_barrier = 1  # volver a place_bridge_ore
                self.mode = 8
                return

        if c.can_build_bridge(place, end):
            c.build_bridge(place, end)
            self.last_bridge_end = end
            self.pending_launcher_bridges.append(place)
            self.last_bridge_built_pos = place
            self.bridge_destination = None  # limpiar tras construir
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
        # --- Selección del destino (barata, sin llamadas al motor) ---
        target_end = self._find_best_bridge_end(bridge_end, c)

        if target_end is None:
            dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        c.draw_indicator_dot(target_end, 255, 255, 0)

        if c.is_in_vision(bridge_end):
            if not self._clear_tile(c, bridge_end):
                return  # Aún no lo hemos roto

        # --- Solo si el puente directo no alcanza, buscar paso intermedio ---
        if c.can_build_bridge(bridge_end, target_end):
            end = target_end
        else:
            end = self._find_bridge_step(bridge_end, target_end, c)
            if end is None:
                dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
                next_pos = current.add(dir)
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
                if c.can_move(dir):
                    c.move(dir)
                return

        # Si ya tenemos un destino fijo guardado (volvemos del modo 8), usarlo
        if self.bridge_destination is not None:
            end = self.bridge_destination

        # Quitar barrier propia en bridge_end si la hay
        building_id_be = c.get_tile_building_id(bridge_end)
        if (building_id_be is not None
                and c.get_entity_type(building_id_be) == EntityType.BARRIER
                and c.get_team(building_id_be) == c.get_team()):
            if c.can_destroy(bridge_end):
                c.destroy(bridge_end)
            return  # Turno siguiente construiremos el puente

        # Primera vez: activar modo 8 para poner barrier en end (si procede)
        if self.bridge_destination is None:
            skip_barrier = (
                end in self.end_bridges
                or (c.is_in_vision(end) and c.get_tile_building_id(end) is not None
                    and c.get_entity_type(c.get_tile_building_id(end)) == EntityType.BRIDGE
                    and c.get_team(c.get_tile_building_id(end)) == c.get_team())
            )
            if not skip_barrier:
                self.pending_barrier_pos = end
                self.bridge_destination = end  # fijar destino
                self.bridge_origin = bridge_end
                self.mode_after_barrier = 2  # volver a bridgeHome
                self.mode = 8
                return

        if c.can_build_bridge(bridge_end, end):
            c.build_bridge(bridge_end, end)
            self.last_bridge_end = end
            self.last_bridge_built_pos = bridge_end
            self.pending_launcher_bridges.append(bridge_end)
            self.bridge_destination = None  # limpiar tras construir
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
                    elif tile in self.recolectores:
                        self.recolectores.remove(tile)
                        continue
                    elif tile in self.objetivos:
                        self.objetivos.remove(tile)
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
        sentinel_spot = None
        if self.last_bridge_built_pos is not None and not self.sentinel_placed:
            closest = min(
                [p for p in candidates if _is_in_bounds(c, p) and self.last_bridge_built_pos != p and c.is_in_vision(p) and (c.is_tile_passable(p) or c.is_tile_empty(p))],
                key=lambda p: p.distance_squared(self.last_bridge_built_pos),
                default=None
            )
            sentinel_spot = closest

        for objetivo in candidates:
            if not _is_in_bounds(c, objetivo):
                continue

            # Acercarnos si no está en visión
            if not c.is_in_vision(objetivo):
                dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                if c.can_move(dir):
                    c.move(dir)
                return

            if c.get_tile_env(objetivo) == Environment.WALL:
                continue

            building_id = c.get_tile_building_id(objetivo)
            edificio_deseado = EntityType.SENTINEL if objetivo == sentinel_spot else EntityType.BARRIER

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

    # MODE 8

    def poner_barrier_adelantada(self, c: Controller):
        """
        Modo 8: va a pending_barrier_pos, pone una barrier, y vuelve al modo anterior.
        Si la casilla ya es nuestra (barrier/puente aliado) o es end_bridge, skip directo.
        """
        target = self.pending_barrier_pos
        if target is None:
            self.mode = self.mode_after_barrier
            return

        # Skip si ya es nuestra o es la base
        if target in self.end_bridges:
            self.pending_barrier_pos = None
            self.mode = self.mode_after_barrier
            return

        if c.is_in_vision(target):
            building_id = c.get_tile_building_id(target)
            if building_id is not None:
                entity = c.get_entity_type(building_id)
                team = c.get_team(building_id)
                if team == c.get_team() and entity in (EntityType.BARRIER, EntityType.BRIDGE):
                    self.pending_barrier_pos = None
                    self.mode = self.mode_after_barrier
                    return

        # Acercarse si no está en visión
        current = c.get_position()
        if not c.is_in_vision(target):
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        # Delegar en construir()
        resultado = self.construir(c, target, EntityType.BARRIER)
        if resultado:
            self.pending_barrier_pos = None
            self.mode = self.mode_after_barrier

    # UTILITY
    def construir(self, c: Controller, objetivo: Position, edificio: EntityType) -> bool:
        """
        Intenta construir 'edificio' en 'objetivo'.

        Flujo:
        1. Si la casilla ya tiene el edificio propio deseado → True (ya está hecho).
        2. Si hay una road propia → la destruye y retorna False (construirá el turno siguiente).
        3. Si hay una road enemiga → se pone encima, la ataca; si la destruyó, sale a una
            casilla adyacente y retorna False (construirá el turno siguiente).
        4. Casilla vacía → se acerca si hace falta y construye → True.
        5. Cualquier otro edificio (irrompible o que no queremos quitar) → True (skip permanente).

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
                        return True # skip permanente: inalcanzable
                    c.draw_indicator_line(current, objetivo, 0, 100, 0)  # verde oscuro
                    dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    if c.can_move(dir):
                        c.move(dir)
                    return False  # Nos acercamos primero

                if c.can_destroy(objetivo):
                    c.destroy(objetivo)
                return False  # El turno siguiente la casilla estará vacía

            # ── 3. Road enemiga: ponerse encima y atacar ─────────────────────────
            if entity == EntityType.ROAD and team != c.get_team():
                if current != objetivo:
                    if c.is_tile_passable(objetivo):
                        c.draw_indicator_line(current, objetivo, 0, 100, 0)  # verde oscuro
                        dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                        next_pos = current.add(dir)
                        if c.can_build_road(next_pos):
                            c.build_road(next_pos)
                        if c.can_move(dir):
                            c.move(dir)
                    return False  # Aún no estamos encima

                # Estamos encima: atacar
                if c.can_fire(objetivo):
                    c.fire(objetivo)

                # Si se destruyó, salir a una casilla adyacente para poder construir
                if c.get_tile_building_id(objetivo) is None:
                    for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
                        adj = objetivo.add(d)
                        if _is_in_bounds(c, adj):
                            dir = self.navegador.moveTo(c, adj, four_dirs=False)
                            if c.can_move(dir):
                                c.move(dir)
                                break

                return False  # El turno siguiente construiremos

            # ── 5. Cualquier otro edificio: skip permanente ──────────────────────
            return True

        # ── 4. Casilla vacía: acercarse y construir ──────────────────────────────
        if current.distance_squared(objetivo) > 2:
            c.draw_indicator_line(current, objetivo, 0, 100, 0)  # verde oscuro
            dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return False

        if current == objetivo:
            dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)

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

    def _is_connected_to_base(self, c: Controller, bridge_id) -> bool:
        """
        Sigue la cadena de puentes desde bridge_id hasta su endpoint final.
        Devuelve True si ese endpoint está en end_bridges (conectado a la base).
        """
        visited = set()
        current_id = bridge_id

        while current_id is not None:
            pos = c.get_position(current_id)
            if pos in visited:
                break  # Ciclo inesperado; evitar bucle infinito
            visited.add(pos)

            endpoint = c.get_bridge_target(current_id)
            if endpoint is None:
                break

            if endpoint in self.end_bridges:
                return True

            if not c.is_in_vision(endpoint):
                break  # No podemos verificar más allá

            next_id = c.get_tile_building_id(endpoint)
            if next_id is None or c.get_entity_type(next_id) != EntityType.BRIDGE:
                break  # La cadena termina aquí y no llegó a end_bridges

            current_id = next_id

        return False

    def _find_best_bridge_end(self, place: Position, c: Controller) -> Position | None:
        """
        Primero intenta conectar a un puente aliado cercano que ya esté conectado
        a la base. Si no encuentra ninguno, usa el comportamiento original
        (apuntar directamente a end_bridges).
        """
        # ── 1. Buscar puentes aliados cercanos conectados a la base ──────────────
        chain_candidates = []
        builds = c.get_nearby_buildings()

        for b in builds:
            if c.get_team(b) != c.get_team():
                continue
            if c.get_entity_type(b) != EntityType.BRIDGE:
                continue

            b_pos = c.get_position(b)
            if place.distance_squared(b_pos) > 9:
                continue  # Fuera del alcance directo de un puente
            if b_pos == self.last_bridge_end:
                continue  # Evitar conectar al puente que acabamos de poner

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
            if _is_in_bounds(c, end):
                return end

        return None

    def _find_bridge_step(self, place: Position, target: Position, c: Controller) -> Position | None:
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
                if not _is_in_bounds(c, candidate) or not c.is_in_vision(candidate):
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

        # Puentes aliados visibles: si la boca está a dist² ≤ 9 y su chain-end
        # supera al mejor candidato directo, úsala como destino.
        builds = c.get_nearby_buildings()
        for b in builds:
            if c.get_team(b) != c.get_team():
                continue
            if c.get_entity_type(b) != EntityType.BRIDGE:
                continue

            b_pos = c.get_position(b)
            if place.distance_squared(b_pos) > 9:
                continue  # fuera de alcance directo, no sirve como end

            # Seguir la cadena hasta el endpoint final
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