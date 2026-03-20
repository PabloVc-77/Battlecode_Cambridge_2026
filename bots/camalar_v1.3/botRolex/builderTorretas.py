from cambc import Controller, Direction, EntityType, Environment, Position
import math

def run_builder_torretas(self, c: Controller):
    if self.my_core is None:
        buildings = c.get_nearby_buildings()
        for b in buildings:
            if c.get_entity_type(b) == EntityType.CORE:
                self.my_core = c.get_position(b)

        w = c.get_map_width()
        h = c.get_map_height()

        x = self.my_core.x
        y = self.my_core.y

        # Vertical Simetry
        self.enemy_core.append(Position(w - x, y))
        # Horizontal Simetry
        self.enemy_core.append(Position(x, h - y))
        # Diagonal Simetry
        self.enemy_core.append(Position(w - x, h - y))

    if self.enemy_core_pos is None:
        find_enemy_core(self, c)
    else:
        #objetivo = self.enemy_core_adjacent[self.analysis_tile]
        find_enemy_tile(self, c)
        place_torreta(self, c)
        c.draw_indicator_dot(self.enemy_core_pos, 245, 63, 39)

    pass

def find_enemy_core(self, c: Controller):
    enemyC = self.enemy_core[self.simetry % 3] # %3 por seguridad

    dir = self.navegador.moveTo(c, enemyC, False)
    move_pos = c.get_position().add(dir)
    if(c.can_build_road(move_pos)):
        c.build_road(move_pos)
    if(c.can_move(dir)):
        c.move(dir)

    if(c.is_in_vision(enemyC)):
        id = c.get_tile_building_id(enemyC)
        if(c.get_entity_type(id) == EntityType.CORE):
            self.enemy_core_pos = enemyC
            add_adjacent_to_core(self, c)
            self.analysis_mode = 0
        else:
            self.simetry += 1

    buildings = c.get_nearby_buildings()
    for b in buildings:
        if(c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team()):
            self.enemy_core_pos = c.get_position(b)
            add_adjacent_to_core(self, c)


def add_adjacent_to_core(self, c: Controller):
    # Agregar a la lista de posiciones a colocar torretas las 16 casillas alrededor del core enemigo (tiene tamaño 3x3) (o menos si esta en el borde)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            pos = Position(self.enemy_core_pos.x + dx, self.enemy_core_pos.y + dy)
            if pos.x >= 0 and pos.x < c.get_map_width() and pos.y >= 0 and pos.y < c.get_map_height():
                difx = abs(pos.x - self.enemy_core_pos.x)
                dify = abs(pos.y - self.enemy_core_pos.y)
                if difx <= 1 and dify <= 1:
                    continue
                self.enemy_core_adjacent.append(pos)
    
def find_enemy_tile(self, c: Controller):
    pass
def place_torreta(self, c: Controller):
    # Poner torreta
    # Escanear las 16 casillas alrededor del core enemigo
    for pos in self.enemy_core_adjacent:
        coreDir = pos.direction_to(self.enemy_core_pos)
        if c.can_build_gunner(pos,coreDir):
            c.build_gunner(pos,coreDir)
            return
        elif c.get_position().distance_squared(pos) >= 2:
            dir = self.navegador.moveTo(c,pos,False)
            if c.can_build_road(c.get_position().add(dir)):
                c.build_road(c.get_position().add(dir))
            if c.can_move(dir):
                c.move(dir)
            return
    # Si hay una casilla vacia con rail conectado a esa casilla, poner torreta
    # Si no, si alguna de las 16 es un rail que esta conectado a otro rail, romper rail
    # Si no, poner torreta en casilla vacia
    pass