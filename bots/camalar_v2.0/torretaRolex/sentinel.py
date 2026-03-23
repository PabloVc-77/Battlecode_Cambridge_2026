from cambc import Controller, Direction, EntityType, Environment, Position
import math

def run_sentinel(self, c: Controller):
    TORRETAS = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]
    #objetivos según prioridad: torreta enemiga, core enemigo, puentes enemigos, todo el resto de cosas enemigas
    #hacer c.get_nearby_buildings() pero solo guardar los que sean del rival
    entities = c.get_nearby_entities()

    for e in entities:
        if c.get_team(e) != c.get_team():
            if c.get_entity_type(e) in TORRETAS:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            elif c.get_entity_type(e) == EntityType.CORE:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            elif c.get_entity_type(e) == EntityType.FOUNDRY:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            elif c.get_entity_type(e) == EntityType.BUILDER_BOT:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            elif c.get_entity_type(e) == EntityType.BRIDGE:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            elif c.get_entity_type(e) == EntityType.ARMOURED_CONVEYOR:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            elif c.get_entity_type(e) in [EntityType.ROAD, EntityType.CONVEYOR, EntityType.SPLITTER]:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))
            else:
                if c.can_fire(c.get_position(e)):
                    c.fire(c.get_position(e))