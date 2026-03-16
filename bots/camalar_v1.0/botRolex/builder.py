from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import bugnav
import random

def run_builder(self, c: Controller):
    #logica del builder aqui
        target = oreCerca(c)
        if  (target != 0):
            siguiente_dir = self.navegador.moveTo(c, target, four_dirs=True)
            move_pos = c.get_position().add(siguiente_dir)
            if c.can_build_harvester(move_pos):
                c.build_harvester(move_pos)
            else:
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)
                if c.can_move(siguiente_dir):
                    c.move(siguiente_dir)
            
        else:
            DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
            move_dir = random.choice(DIRECTIONS)
            move_pos = c.get_position().add(move_dir)
            # we need to place a conveyor or road to stand on, before we can move onto a tile
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)
        pass



def oreCerca(c: Controller):
    # lógica para identificar ores aqui
    lista = c.get_nearby_tiles()
    pos = 0
    for tile in lista:
        if c.get_tile_env(tile) in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            pos = tile 
    return pos