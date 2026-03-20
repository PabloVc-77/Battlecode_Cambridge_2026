from cambc import Controller, Direction, EntityType, Environment, Position

def run_core(self, c: Controller):
    # Spawn a builder on an empty core tile
    #ident_near_ores(c)

    if c.get_current_round() >= 50 and c.get_current_round() <= 100 and self.num_tbuilders < 3:
        if spawnBuilder(self, c):
            self.num_tbuilders += 1

    if self.num_spawned < 5:
        spawnBuilder(self, c)
    elif c.get_current_round() % 35 == 0:  # Example round number, replace with actual condition
        spawnBuilder(self, c)
        
    recursos = c.get_global_resources()
    if 2 * c.get_harvester_cost()[0] + c.get_builder_bot_cost()[0] <= recursos[0]  and c.get_current_round() > 700 : 
        spawnBuilder(self, c)

def spawnBuilder(self, c:Controller):
    pos = c.get_position()  # centre of the 3x3 core
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            target = Position(pos.x + dx, pos.y + dy)
            if c.can_spawn(target):
                c.spawn_builder(target)
                self.num_spawned += 1
                return True
    return False

def ident_near_ores(c: Controller):
    # lógica para identificar ores aqui
    lista = c.get_nearby_tiles()
    enterolargo = 0
    centro = c.get_position()
    cx = centro.x
    cy = centro.y
    for tile in lista:
        if c.get_tile_env(tile) == (Environment.ORE_TITANIUM or Environment.ORE_AXIONITE):
            enterolargo = tile.x * 100 + tile.y

    pos_1 = Position(cx + 2, cy + 2)
    pos_2 = Position(cx - 2, cy + 2)
    pos_3 = Position(cx + 2, cy - 2)
    pos_4 = Position(cx - 2, cy - 2)
    if c.can_place_marker(pos_1):
        c.place_marker(pos_1, enterolargo)
    elif c.can_place_marker(pos_2):
        c.place_marker(pos_2, enterolargo)
    elif c.can_place_marker(pos_3):
        c.place_marker(pos_3, enterolargo)
    elif c.can_place_marker(pos_4):
        c.place_marker(pos_4, enterolargo)
        
    pass