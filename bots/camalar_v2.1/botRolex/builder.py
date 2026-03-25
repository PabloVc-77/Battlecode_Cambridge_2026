from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bignav_opus as bugnav

def run_builder(self, c: Controller):
    #logica del builder aqui
    if self.mode == 1:
        # place bridge near ore
        place_bridge_ore(self, c)
        return
    elif self.mode == 2:
        # go home
        bridgeHome(self, c)
        return
    elif self.mode == 3:
        # Revisar camino a casa
        revisar_camino_casa(self, c)
        return
    elif self.mode == 4:
        place_conveyors(self, c)
        return

    oreCerca(self, c)
    current = c.get_position()
    target = None
    entityID = c.get_tile_building_id(current)
    tileTeam = c.get_team(entityID)
    if tileTeam is not None and tileTeam != c.get_team() and c.get_entity_type(entityID) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER]:
        if c.can_fire(current):
            c.fire(current)
        return

    if len(self.objetivos) > 0:
        target = self.objetivos[0]
    elif len(self.recolectores) > 0:
        target = self.recolectores[0]
    else:
        target = None

    if  (target is not None):
        c.draw_indicator_line(current, target, 204, 39, 245)
        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
        move_pos = current.add(siguiente_dir)
        c.draw_indicator_line(current, move_pos, 66, 245, 39)

        if c.is_in_vision(target):
            b_id = c.get_tile_building_id(target)
            if c.get_entity_type(b_id) == EntityType.ROAD and c.get_team(b_id) == c.get_team() and c.can_destroy(target):
                c.destroy(target)

            if current == target and (b_id is None or c.get_team(b_id) == c.get_team()):
                dir = self.navegador.moveDvD(c, False)
                if c.can_move(dir):
                    c.move(dir)

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
            # (ya hay uno, o el tile cambió) → descartar y buscar otro
            
            b_id = c.get_tile_building_id(target)
            if b_id is not None and c.get_entity_type(b_id) == EntityType.HARVESTER and not revisor_casillas_extractor(c, c.get_position(b_id)):
                self.current_target = target
                if target in self.objetivos:
                    self.objetivos.remove(target)
                if target in self.recolectores:
                    self.recolectores.remove(target)
                self.mode = 1
                return
            elif c.is_tile_passable(target) and b_id is not None and c.get_team(b_id) != c.get_team():
                if c.can_fire(target):
                    c.fire(target)
                else:
                    dir = self.navegador.moveTo(c, target, False)
                    if c.can_move(dir):
                        c.move(dir)

            if target in self.objetivos:
                self.objetivos.remove(target)
            self.current_target = None
        
    else:
        move_dir = self.navegador.moveDvD(c, four_dirs=False)
        move_pos = current.add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(move_dir):
            c.move(move_dir)
    pass

def place_bridge_ore(self, c: Controller):
    places = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
    viable_places = []
    for d in places:
        spot = self.current_target.add(d)
        if _is_in_bounds(c, spot) and c.is_in_vision(spot):
            something = c.get_tile_building_id(spot)
            something2 = c.get_tile_env(spot)
            if something is None or (c.get_team(something) == c.get_team() and c.get_entity_type(something) in [EntityType.ROAD]):
                if something2 not in [Environment.ORE_AXIONITE, Environment.ORE_TITANIUM]:
                    viable_places.append(spot)
    
    if len(viable_places) == 0:
        self.current_target = None
        self.mode = 0
        return
    
    current = c.get_position()
    viable_places.sort(key=lambda p: current.distance_squared(p))
    place = viable_places[0]
    c.draw_indicator_dot(place, 0, 0, 0)

    if place == current:
        dir = self.navegador.moveTo(c, self.spawn, False)
        if c.can_move(dir):
            c.move(dir)

    quitar = c.get_tile_building_id(place)
    if quitar is not None:
        if c.can_destroy(place):
            c.destroy(place)
        else:
            dir = self.navegador.moveTo(c, place, False)
            if c.can_move(dir):
                c.move(dir)
    elif current.distance_squared(place) > 2:
        dir = self.navegador.moveTo(c, place, False)
        if c.can_move(dir):
            c.move(dir)

    self.end_bridges.sort(key=lambda p: place.distance_squared(p))
    end = _find_viable_bridge_end(self.end_bridges, place, self.end_bridges, c)
    if end is None:
        self.mode = 0
        return
    
    # Al final de place_bridge_ore, después de calcular end:
    conv_path = _is_conv_better(c, place, end)
    self.conveyor_path = conv_path
    if conv_path is not None and len(conv_path) > 0:
        conv_pos, conv_dir = conv_path[0]
        if c.can_build_conveyor(conv_pos, conv_dir):
            c.build_conveyor(conv_pos, conv_dir)
            self.conveyor_path.pop()
            self.last_bridge_end = conv_pos.add(conv_dir)
        self.mode = 4  # la siguiente búsqueda decide el resto  
        return

    if c.can_build_bridge(place, end):
        c.build_bridge(place, end)
        self.last_bridge_end = end
        self.mode = 2

        if end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None
        elif c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            self.mode = 3

    c.draw_indicator_dot(end, 255, 255, 255)
    if c.can_build_bridge(place, end):
        c.build_bridge(place, end)
        self.last_bridge_end = end
        self.mode = 2

        if end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None
        elif c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            self.mode = 3


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

    # Calcular end del siguiente puente
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

    # Limpiar tile si hay algo
    something = c.get_tile_building_id(bridge_end)
    if something is not None:
        if c.can_destroy(bridge_end):
            c.destroy(bridge_end)
        elif c.can_fire(bridge_end):
            c.fire(bridge_end)
        else:
            dir = self.navegador.moveTo(c, bridge_end, False)
            if c.can_move(dir):
                c.move(dir)

    # ¿Conveyors más baratas para este tramo (bridge_end → end)?
    conv_path = _is_conv_better(c, bridge_end, end)
    self.conveyor_path = conv_path
    if conv_path is not None and len(conv_path) > 0:
        conv_pos, conv_dir = conv_path[0]
        if c.can_build_conveyor(conv_pos, conv_dir):
            c.build_conveyor(conv_pos, conv_dir)
            self.conveyor_path.pop()
            self.last_bridge_end = conv_pos.add(conv_dir)
        # No actualizamos last_bridge_end — la siguiente búsqueda decide el resto
        self.mode = 4
        return

    # Puente normal
    if c.can_build_bridge(bridge_end, end):
        c.build_bridge(bridge_end, end)
        self.last_bridge_end = end

        if end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None
        elif c.get_entity_type(c.get_tile_building_id(end)) in (EntityType.BRIDGE, EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
            self.mode = 3

def oreCerca(self, c: Controller):
    # lógica para identificar ores aqui
    lista = c.get_nearby_tiles()
    for tile in lista:
        if c.get_tile_env(tile) == Environment.ORE_TITANIUM or (c.get_tile_env(tile) == Environment.ORE_AXIONITE and c.get_current_round() >= 100):
            #and c.get_tile_building_id(tile) is None:
            building_id = c.get_tile_building_id(tile)

            if(building_id is not None): # Hay algo
               if ( c.get_entity_type(building_id) == EntityType.HARVESTER): # Hay un harvester
                    if not revisor_casillas_extractor(c, tile):  # No hay puentes
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
    pass

# MODE 3

def revisar_camino_casa(self, c: Controller):
    current = c.get_position()

    # Inicializar check_pos si es la primera vez que entramos
    if self.check_pos is None:
        self.check_pos = self.last_bridge_end

    if self.check_pos is None:
        self.mode = 0
        return

    # ¿Ya llegamos a spawn?
    if self.check_pos in self.end_bridges:
        self.mode = 0
        self.check_pos = None
        self.last_bridge_end = None
        return

    c.draw_indicator_dot(self.check_pos, 255, 128, 0)

    # Si no tenemos visión, movernos hacia check_pos
    if not c.is_in_vision(self.check_pos):
        dir = self.navegador.moveTo(c, self.check_pos, four_dirs=False)
        next_pos = current.add(dir)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(dir):
            c.move(dir)
        return

    # Tenemos visión — comprobar qué hay en check_pos
    building_id = c.get_tile_building_id(self.check_pos)

    if building_id is None or c.get_entity_type(building_id) not in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR):
        # Hueco — reconstruir desde aquí
        self.last_bridge_end = self.check_pos
        self.check_pos = None
        self.mode = 2
        return

    if c.get_team(building_id) != c.get_team():
        # Puente enemigo — reconstruir desde aquí
        self.last_bridge_end = self.check_pos
        self.check_pos = None
        self.mode = 2
        return

    # Puente nuestro y válido — avanzar al siguiente eslabón
    if c.get_entity_type(building_id) == EntityType.BRIDGE:
        next_check = c.get_bridge_target(building_id)
    else:
        next_check = self.last_bridge_end.add(c.get_direction(building_id))

    if next_check is None:
        self.last_bridge_end = self.check_pos
        self.check_pos = None
        self.mode = 2
        return

    # Todo bien en este eslabón, avanzar
    self.check_pos = next_check

def revisor_casillas_extractor (c: Controller, pos: Position):
    # lógica para revisar casillas alrededor del extractor
    Existe = False
    casillas = [pos.add(Direction.NORTH), pos.add(Direction.EAST), pos.add(Direction.SOUTH), pos.add(Direction.WEST)]

    for casilla in casillas:
        if _is_in_bounds(c, casilla):
            if c.is_in_vision(casilla):
                building_id = c.get_tile_building_id(casilla)
                if building_id is not None and c.get_entity_type(building_id) == EntityType.BRIDGE and c.get_team(building_id) == c.get_team():
                    Existe = True
                    break
            else:
                Existe = True
                break
    return Existe            

# MODE 4
def place_conveyors(self, c: Controller):

    if len(self.conveyor_path) == 0:
        self.mode = 2
        return

    conv_pos, conv_dir = self.conveyor_path[0]
    
    build_id = c.get_tile_building_id(conv_pos)
    if build_id is not None:
        if c.get_team() == c.get_team(build_id):
            if c.can_destroy(conv_pos):
                c.destroy(conv_pos)
        elif c.can_fire(conv_pos):
            c.fire(conv_pos)

    if c.can_build_conveyor(conv_pos, conv_dir):
        c.build_conveyor(conv_pos, conv_dir)
        self.conveyor_path.pop()
        end = conv_pos.add(conv_dir)

        if end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None
            return
        
        if len(self.conveyor_path) == 0:
            build_id = c.get_tile_building_id(end)
            if c.get_entity_type(build_id) not in (EntityType.BRIDGE, EntityType.ARMOURED_CONVEYOR, EntityType.CONVEYOR) or c.get_team() != c.get_team(build_id):
                self.mode = 2
                self.last_bridge_end = end
                return
            else:
                self.mode = 3
                return

    return

def _is_conv_better(c: Controller, ini: Position, end: Position):
    """
    BFS desde ini hasta end. En cada paso el coste acumulado es:
        (i + 0.01 * i) * conveyor_cost  donde i = número de pasos
    Si encontramos camino antes de superar bridge_cost, devuelve
    lista de (pos, dir) para colocar las conveyors. Si no, None.
    """
    bridge_cost = c.get_bridge_cost()[0]
    conveyor_cost = c.get_conveyor_cost()[0]

    # Cola BFS: (posición_actual, camino_hasta_aquí)
    # camino es lista de (pos, dir) — la dir que tomamos AL LLEGAR a pos
    from collections import deque
    queue = deque()
    queue.append((ini, []))
    visited = {ini}

    while queue:
        current, path = queue.popleft()

        i = len(path)
        coste_acumulado = (i + 0.01 * i) * conveyor_cost
        if coste_acumulado > bridge_cost:
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

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()

    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

def _find_viable_bridge_end(end_of_bridges, place: Position, candidates: list, c: Controller) -> Position | None:
    """
    Dado `place` y una lista de destinos candidatos (end_bridges ordenados por
    distancia), devuelve el primer end válido, o None si ninguno sirve.
    """
    for target in candidates:
        end = _get_end_of_bridge(end_of_bridges, place, target, c)
        if end is not None:
            return end
    return None

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
                    if c.get_entity_type(building_id) not in (EntityType.ROAD,EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.SPLITTER, EntityType.FOUNDRY):
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