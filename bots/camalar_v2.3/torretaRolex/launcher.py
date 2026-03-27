from cambc import Controller, Direction, EntityType, Environment, Position

class Launcher:
    def __init__(self, c: Controller):
        current = c.get_position()
        self.semi_spawn = current  # fallback por defecto
        self.my_bridge = current   # fallback

        buildings = c.get_nearby_buildings()
        my_bridges = []
        for b in buildings:
            if c.get_entity_type(b) == EntityType.BRIDGE and c.get_team(b) == c.get_team():
                my_bridges.append(b)

        my_bridges.sort(key=lambda p: current.distance_squared(c.get_position(p)))

        if len(my_bridges) == 0:
            return

        my_b = my_bridges[0]
        self.my_bridge = c.get_position(my_b)

        next_bridge = c.get_bridge_target(my_b)

        while c.is_in_vision(next_bridge):
            b_id = c.get_tile_building_id(next_bridge)
            if b_id is None or c.get_entity_type(b_id) != EntityType.BRIDGE:
                break
            next_bridge = c.get_bridge_target(b_id)

        self.semi_spawn = next_bridge

    def run(self, c: Controller):
        viable_launching_places = c.get_nearby_tiles()
        # Más lejos de semi_spawn primero → queremos lanzar lejos
        viable_launching_places.sort(key=lambda p: self.semi_spawn.distance_squared(p), reverse=True)

        units = c.get_nearby_units(2)
        # Priorizar bots enemigos más cercanos a nuestro bridge
        units.sort(key=lambda u: self.my_bridge.distance_squared(c.get_position(u)))

        for u in units:
            if c.get_team(u) != c.get_team():
                for place in viable_launching_places:
                    if c.can_launch(c.get_position(u), place):
                        c.launch(c.get_position(u), place)
                        return