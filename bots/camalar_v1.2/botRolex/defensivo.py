from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bugnav4_opus as bugnav


#get_tile_env(pos: Position) == None

def run_defensivo(self, c: Controller):

    if(self.my_core is None):
        c.get_position()
        casillas = c.get_nearby_buildings()
        #obtener posición del nodo
        for nodeID in casillas:
            if c.get_entity_type(nodeID) == EntityType.CORE:
                self.my_core = c.get_position(nodeID)
                break
    
    if self.my_core is None:
        return

    nodePosition = self.my_core

    direc = self.navegador.moveTo(c, nodePosition, four_dirs= False)  

    circulo = obtener_anillo_16_casillas(c, nodePosition)
    circulo = sorted(circulo, key=lambda p: c.get_position().distance_squared(p))
    obj = None
    if len(circulo) > 0:
        obj = circulo[0]

    if obj is not None:
        if c.can_build_conveyor(obj, obj.direction_to(nodePosition)):
            c.build_conveyor(obj, obj.direction_to(nodePosition))
        else:
            direc = self.navegador.moveTo(c, obj, four_dirs= False)

    if(c.can_move(direc)):
        c.move(direc)
                


def obtener_anillo_16_casillas(c: Controller, centro: Position):
    cx = centro.x
    cy = centro.y
    casillas_validas = []
    
    # Recorremos un área de 5x5 alrededor del centro (desde -2 hasta +2)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            # TRUCO: Si la distancia máxima en x o en y es exactamente 2, 
            # significa que estamos en el borde exterior (las 16 casillas que quieres).
            if max(abs(dx), abs(dy)) == 2:
                pos = Position(cx + dx, cy + dy)
                
                # Comprobamos que no se salga del mapa por si el Nexo está en una esquina
                if c.is_in_vision(pos) and c.is_tile_empty(pos):
                    casillas_validas.append(pos)
                    
    return casillas_validas