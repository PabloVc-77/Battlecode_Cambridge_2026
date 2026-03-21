from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math

def run_builder(self, c: Controller):
    #logica del builder aqui
    oreCerca(self, c)
    current = c.get_position()
    target = None
    entityID = c.get_tile_building_id(current)
    tileTeam = c.get_team(entityID)
    if tileTeam is not None and tileTeam != c.get_team() and c.get_entity_type(entityID) == EntityType.CONVEYOR:
        c.self_destruct()
        return

    if len(self.objetivos) > 0:
        target = self.objetivos[0]
    else:
        target = None

    if  (target is not None):
        c.draw_indicator_line(current, target, 204, 39, 245)
        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=True)
        move_pos = current.add(siguiente_dir)
        c.draw_indicator_line(current, move_pos, 66, 245, 39)
        if c.can_build_harvester(target) and current.distance_squared(target) < 2:
            c.build_harvester(target)
            if target in self.objetivos:
                self.objetivos.remove(target)
            self.current_target = None
        elif(math.sqrt(current.distance_squared(target)) > math.sqrt(2)):
            if c.can_build_conveyor(move_pos, siguiente_dir.opposite()):
                c.build_conveyor(move_pos, siguiente_dir.opposite())
            else:
                estructura = c.get_tile_building_id(move_pos)
                if c.get_entity_type(estructura) == EntityType.ROAD and c.can_destroy(move_pos):
                    c.destroy(move_pos)
                    if c.can_build_conveyor(move_pos, siguiente_dir.opposite()):
                        c.build_conveyor(move_pos, siguiente_dir.opposite())

            if c.can_move(siguiente_dir):
                c.move(siguiente_dir)
        else:
            # Estamos al lado del target pero no podemos construir harvester
            # (ya hay uno, o el tile cambió) → descartar y buscar otro
            if target in self.objetivos:
                self.objetivos.remove(target)
            self.current_target = None
        
    else:
        move_dir = self.navegador.moveDvD(c, four_dirs=True)
        move_pos = current.add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if c.can_build_conveyor(move_pos, move_dir.opposite()):
            c.build_conveyor(move_pos, move_dir.opposite())
        if c.can_move(move_dir):
            c.move(move_dir)
    pass

def conveyorHome(self, c: Controller):
    current = c.get_position()
    dir = self.navegador.moveTo(c, self.spawn, four_dirs=True)
    next_Pos = current.add(dir)
    
    if(c.can_move(dir)):
        c.move(dir)
    elif(c.can_build_road(next_Pos)):
        c.build_road(next_Pos)
        if(c.can_move(dir)):
            c.move(dir)

    if(c.get_entity_type(c.get_tile_building_id(current)) == EntityType.ROAD and c.can_destroy(current)):
        c.destroy(current)

    if(c.can_build_conveyor(current, dir)):
        c.build_conveyor(current, dir)
    else:
        pass        

    if(next_Pos == self.spawn):
        self.conveyor_mode = False
        
    pass

def oreCerca(self, c: Controller):
    # lógica para identificar ores aqui
    lista = c.get_nearby_tiles()
    for tile in lista:
        if c.get_tile_env(tile) in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            #and c.get_tile_building_id(tile) is None:
            building_id = c.get_tile_building_id(tile)

            if(building_id is not None):
                if c.get_entity_type(building_id) != None:
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