from cambc import Controller, Direction, EntityType, Environment, Position

def run_core(self, c: Controller):
        # Spawn a builder on an empty core tile
    for i in range(9):
        pos = c.get_position()  # centre of the 3x3 core
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                target = Position(pos.x + dx, pos.y + dy)
                if c.can_spawn(target):
                    c.spawn_builder(target)
                    self.num_spawned += 1
                    break
    # lógica del core aqui



def ident_near_ores(c: Controller):
    # lógica para identificar ores aqui
    lista = c.get_nearby_tiles()
    enterolargo = 0
    pos = c.get_position()  # centre de la core
    pos.x = pos.x  + 2
    pos.y = pos.y  + 2
    for tile in lista:
        if c.get_tile_env(tile) == (Environment.ORE_TITANIUM or Environment.ORE_AXIONITE):
            enterolargo = tile.x * 100 + tile.y

    if c.can_place_marker(pos):
        c.place_marker(pos, enterolargo)
    pass