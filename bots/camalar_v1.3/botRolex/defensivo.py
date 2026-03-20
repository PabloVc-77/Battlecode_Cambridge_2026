from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math

#get_tile_env(pos: Position) == None

def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0

def run_defensivo(self, c: Controller):

    if(self.my_core is None):
        casillas = c.get_nearby_buildings()
        #obtener posición del nodo
        for nodeID in casillas:
            if c.get_entity_type(nodeID) == EntityType.CORE:
                self.my_core = nodeID
                break
    
    if self.my_core is None:
        return

    nodePosition = c.get_position(self.my_core)
    if(c.get_hp(self.my_core) < c.get_max_hp(self.my_core) and c.can_heal(nodePosition)):
        c.heal(nodePosition)

    current = c.get_position()
    direc = current.direction_to(nodePosition)

    # AXIONITE MISION
    entradas = is_there_axionite(c, nodePosition)
    if(len(entradas) > 0 or self.furnace):
        self.furnace = True
        if self.splitter_pos is None:
            self.splitter_pos = entradas[0]
        mision_axionite(self, c, nodePosition)
        return

    circulo = obtener_anillo_16_casillas(c, nodePosition)
    circulo = sorted(circulo, key=lambda p: c.get_position().distance_squared(p))
    obj = None
    if len(circulo) > 0:
        obj = circulo[0]
    
    if obj is not None:
        c.draw_indicator_dot( obj, 186, 227, 0)
        cdir = obj.direction_to(nodePosition)
        if _is_diagonal(cdir):
            cdir = cdir.rotate_left()
            
        if c.can_build_conveyor(obj, cdir):
            c.build_conveyor(obj, cdir)
        else:
            direc = current.direction_to(obj)

    if(c.can_move(direc)):
        c.move(direc)
                
def is_there_axionite(c: Controller, centro: Position):
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
                if c.is_in_vision(pos) and c.get_entity_type(pos) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR]:
                    conveyor = c.get_tile_building_id(pos)
                    material = c.get_stored_resource(conveyor)
                    if material is not None and material == "raw_axionite":
                        casillas_validas.append(pos)
                    
    return casillas_validas

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

def mision_axionite(self, c: Controller, nodePosition: Position):
    splitter_pos = self.splitter_pos
    if self.furnace_pos is None:
        viable_places =  [splitter_pos.add(Direction.NORTH), splitter_pos.add(Direction.EAST), splitter_pos.add(Direction.SOUTH), splitter_pos.add(Direction.WEST)]
        true_viable_places = []
        for vp in viable_places:
            if vp.distance_squared(nodePosition) >= 7:
                true_viable_places.append(vp)

        if len(true_viable_places) == 0:
            self.furnace = False
            return

        self.furnace_pos = true_viable_places[0]
    
    furnace_pos = self.furnace_pos
    current = c.get_position()

    splitter_dir = splitter_pos.direction_to(nodePosition)
    if _is_diagonal(splitter_dir):
        splitter_dir = splitter_dir.rotate_left()

    b_id_at_split = c.get_tile_building_id(splitter_pos)
    
    if(b_id_at_split is not None and c.get_entity_type(b_id_at_split) != EntityType.SPLITTER):
        if c.can_destroy(splitter_pos):
            c.destroy(splitter_pos)
        else:
            direc = current.direction_to(splitter_pos)
            if(c.can_move(direc)):
                c.move(direc)
    elif b_id_at_split is None:
        if c.can_build_splitter(splitter_pos, splitter_dir):
            c.build_splitter(splitter_pos, splitter_dir)
            self.fase2 = True
    
    current = c.get_position()
    b_id_at_furnace = c.get_tile_building_id(furnace_pos)
    if self.fase2:
        if(b_id_at_furnace is not None and c.get_entity_type(b_id_at_furnace) != EntityType.FOUNDRY):
            if c.can_destroy(furnace_pos):
                c.destroy(furnace_pos)
            else:
                direc = current.direction_to(furnace_pos)
                if(c.can_move(direc)):
                    c.move(direc)
        elif b_id_at_furnace is None:
            if c.can_build_foundry(furnace_pos):
                c.build_foundry(furnace_pos)
                self.fase2 = False
                self.furnace = False
            
        