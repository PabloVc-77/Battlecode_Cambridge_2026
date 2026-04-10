from cambc import Controller, Direction, EntityType, Environment, Position
import math

TORRETAS = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]

def run_sentinel(self, c: Controller):
    targets = []

    tiles = c.get_nearby_tiles()
    for t in tiles:
        bot_id = c.get_tile_builder_bot_id(t)
        if bot_id is not None and c.get_team(bot_id) != c.get_team():
            targets.append(t)
        tid = c.get_tile_building_id(t)
        entity = c.get_entity_type(tid)
        if c.get_team(tid) != c.get_team() and entity != EntityType.HARVESTER:
            targets.append(t)
    

    targets.sort(key=lambda e: get_priority(e, c))

    for e in targets:
        try:
            if c.can_fire(e):
                c.fire(e)
                return  # ← añadido: una vez dispara, termina el turno
        except Exception:
            continue  # entidad murió entre iteraciones

def get_priority(e, c: Controller):
    try:
        bot = c.get_tile_builder_bot_id(e)
        t = c.get_entity_type(e)
    except Exception:
        return 999
    if bot is not None and c.get_team(bot) != c.get_team():
        return 4
    if t == EntityType.HARVESTER:
        return 999
    if t in TORRETAS:
        return 1
    if t == EntityType.CORE:
        return 2
    if t == EntityType.FOUNDRY:
        return 3
    if t == EntityType.BUILDER_BOT:
        return 4
    if t == EntityType.BRIDGE:
        return 5
    if t == EntityType.ARMOURED_CONVEYOR:
        return 6
    if t in [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER]:
        return 7
    return 8