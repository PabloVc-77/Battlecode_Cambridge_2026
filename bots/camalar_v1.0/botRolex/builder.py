from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import bugnav
import random

def run_builder(self, c: Controller):
    #logica del builder aqui
    if(self.conveyor_mode): conveyorHome(self, c)
    oreCerca(self, c)
    current = c.get_position()
    target = None
    if(len(self.objetivos) > 0):
        target = self.objetivos[0]

    if  (target is not None):
        siguiente_dir = self.navegador.moveTo(c, target, four_dirs=False)
        move_pos = current.add(siguiente_dir)
        c.draw_indicator_line(current, move_pos, 66, 245, 39)
        if c.can_build_harvester(move_pos):
            c.build_harvester(move_pos)
            self.conveyor_mode = True
        else:
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(siguiente_dir):
                c.move(siguiente_dir)
        
    else:
        move_dir = self.navegador.moveDvD(c)
        move_pos = current.add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
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
        if c.get_tile_env(tile) in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE) and c.get_tile_building_id(tile) is None:
            self.objetivos.append(tile)
    current = c.get_position()
    self.objetivos.sort(key=lambda p: current.distance_squared(p))
    pass