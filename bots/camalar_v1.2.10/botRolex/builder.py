from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()

    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

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

    oreCerca(self, c)
    current = c.get_position()
    target = None
    entityID = c.get_tile_building_id(current)
    tileTeam = c.get_team(entityID)
    if tileTeam is not None and tileTeam != c.get_team() and c.get_entity_type(entityID) in [EntityType.CONVEYOR, EntityType.CONVEYOR, EntityType.SPLITTER]:
        c.self_destruct()
        return

    if len(self.objetivos) > 0:
        target = self.objetivos[0]
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

        if c.can_build_harvester(target) and current.distance_squared(target) <= 2:
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
        self.mode = 0
        return
    
    current = c.get_position()
    viable_places.sort(key=lambda p: current.distance_squared(p))
    place = viable_places[0]
    c.draw_indicator_dot(place, 0, 0, 0)
    dir = Direction.CENTRE
    
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

    self.end_bridges.sort(key=lambda p: place.distance_squared(p))  # ordenar desde place, no current
    end = _find_viable_bridge_end(place, self.end_bridges, c)
    if end is None:
        self.mode = 0  # ningún destino válido, volver a buscar ore
        return
    
    c.draw_indicator_dot(end, 255, 255, 255)
    if c.can_build_bridge(place, end):
        c.build_bridge(place, end)
        self.last_bridge_end = end
        self.mode = 2

        if end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None

def bridgeHome(self, c: Controller):
    current = c.get_position()
    bridge_end = self.last_bridge_end

    if bridge_end is not None and bridge_end.distance_squared(self.spawn) <= 2:
        self.mode = 0
        self.last_bridge_end = None
        return

    # Condición de llegada directa
    if bridge_end.distance_squared(self.spawn) <= 2:
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
    end = _find_viable_bridge_end(bridge_end, self.end_bridges, c)

    if end is None:
        dir = self.navegador.moveTo(c, self.spawn, four_dirs=False)
        next_pos = current.add(dir)
        if c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(dir):
            c.move(dir)
        return

    c.draw_indicator_dot(end, 255, 255, 0)

    something = c.get_tile_building_id(bridge_end)
    if something is not None:
        if c.can_destroy(bridge_end):
            c.destroy(bridge_end)

    if c.can_build_bridge(bridge_end, end):
        c.build_bridge(bridge_end, end)
        self.last_bridge_end = end

        if end in self.end_bridges:
            self.mode = 0
            self.last_bridge_end = None

def oreCerca(self, c: Controller):
    # lógica para identificar ores aqui
    lista = c.get_nearby_tiles()
    for tile in lista:
        if c.get_tile_env(tile) in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            #and c.get_tile_building_id(tile) is None:
            building_id = c.get_tile_building_id(tile)

            if(building_id is not None):
                if not (c.get_entity_type(building_id) == EntityType.ROAD and c.get_team(building_id) == c.get_team()):
                    if tile in self.objetivos:
                        self.objetivos.remove(tile)
                    continue  # saltar este tile


            if tile not in self.objetivos:
                self.objetivos.append(tile)
        elif tile in self.objetivos:
            self.objetivos.remove(tile)
            
    current = c.get_position()
    self.objetivos.sort(key=lambda p: current.distance_squared(p))
    pass

def _get_end_of_bridge(place: Position, target: Position, c: Controller) -> Position | None:
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
                    if c.get_team(building_id) != c.get_team():
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

    return best


def _find_viable_bridge_end(place: Position, candidates: list, c: Controller) -> Position | None:
    """
    Dado `place` y una lista de destinos candidatos (end_bridges ordenados por
    distancia), devuelve el primer end válido, o None si ninguno sirve.
    """
    for target in candidates:
        end = _get_end_of_bridge(place, target, c)
        if end is not None:
            return end
    return None