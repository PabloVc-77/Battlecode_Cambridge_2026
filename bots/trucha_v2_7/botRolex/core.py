from cambc import Controller, Direction, EntityType, Environment, Position

def run_core(self, c: Controller):

    entities = c.get_nearby_entities()
    for e in entities:
        if c.get_entity_type(e) == EntityType.BUILDER_BOT and c.get_team(e) != c.get_team():
            if spawnBuilder(c) and self.num_spawned < 10:
                self.num_spawned += 1
    
    ronda = c.get_current_round()
    if self.num_spawned < 5 and ronda < 100:
        if spawnBuilder(c):
            self.num_spawned += 1
        
    recursos = c.get_global_resources()        

    limite = c.get_foundry_cost()[0] + c.get_builder_bot_cost()[0]

    if limite <= recursos[0] and recursos[0] >= 150 and c.get_current_round() >= 100: 
        if spawnBuilder(c):
            self.num_spawned += 1
    
    ax_limit = 3 * c.get_armoured_conveyor_cost()[1]
    if ronda < 713 and recursos[0] <= limite and recursos[1] > ax_limit:
        c.convert(recursos[1] - ax_limit)

def spawnBuilder(c:Controller):
    pos = c.get_position()  # centre of the 3x3 core
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            target = Position(pos.x + dx, pos.y + dy)
            if c.can_spawn(target):
                c.spawn_builder(target)
                return True
    return False