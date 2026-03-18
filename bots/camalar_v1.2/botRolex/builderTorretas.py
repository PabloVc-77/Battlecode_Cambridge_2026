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
        else:
            self.simetry += 1

    buildings = c.get_nearby_buildings()
    for b in buildings:
        if(c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team()):
            self.enemy_core_pos = c.get_position(b)


def place_torreta(self, c: Controller):
    # Poner torreta
    pass