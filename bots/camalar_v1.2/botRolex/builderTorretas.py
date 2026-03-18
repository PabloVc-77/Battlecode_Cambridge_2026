from cambc import Controller, Direction, EntityType, Environment, Position
import math

def run_builder_torretas(self, c: Controller):
    if self.core_pos is None:
        buildings = c.get_nearby_buildings()
        for b in buildings:
            if c.get_entity_type(b) == EntityType.CORE:
                self.my_core = c.get_position(b)

        w = c.get_map_width
        h = c.get_map_height

        x = self.my_core.x
        y = self.my_core.y

        # Vertical Simetry
        enemyCore = Position(w - x, y)
        if(c.get_entity_type(c.get_tile_building_id(enemyCore)) == EntityType.CORE):
            c.draw_indicator_dot(enemyCore, 245, 63, 39)

    pass