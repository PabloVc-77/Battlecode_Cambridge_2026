from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bugnav4_opus as bugnav


#get_tile_env(pos: Position) == None

def run_defensivo(self, c: Controller):
    c.get_position()
    casillas =c.get_nearby_buildings()
    #obtener posición del nodo
    for tile in casillas:
        nodeID = c.get_tile_building_id(tile)
        if  c.get_entity_type(nodeID) == EntityType.CORE:
            nodePosition =c.get_position(nodeID)
            break
    direc = c.bugnav.moveTo(self, nodePosition, four_dirs= False)  
    c.get_position().add(direc)
    
    
    pass