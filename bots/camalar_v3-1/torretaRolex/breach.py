from cambc import Controller, Direction, EntityType, Environment, Position
import math

TORRETAS = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]

def run_breach(self, c: Controller):
    entities = c.get_nearby_entities()

    targets = []
    for e in entities:
        try:
            team = c.get_team(e)
            tipo = c.get_entity_type(e)
        except Exception:
            continue  # entidad ya no existe
        if team != c.get_team() and tipo != EntityType.HARVESTER:
            targets.append(e)

    targets.sort(key=lambda e: get_priority(e, c))

    for e in targets:
        try:
            pos = c.get_position(e)
            tipo = c.get_entity_type(e)
        except Exception:
            continue  # entidad murió entre iteraciones

        if tipo == EntityType.CORE:
            adjacentes = [
                pos.add(Direction.NORTH),
                pos.add(Direction.SOUTH),
                pos.add(Direction.WEST),
                pos.add(Direction.EAST),
            ]
            adjacentes.sort(key=lambda p: (
                (p.x - c.get_position().x) ** 2 + (p.y - c.get_position().y) ** 2
            ))
            for adj in adjacentes:
                if c.can_fire(adj):
                    c.fire(adj)
                    return
            # Si ninguna adyacente es alcanzable, intentar el centro
            if c.can_fire(pos):
                c.fire(pos)
            return

        if c.can_fire(pos):
            c.fire(pos)
            return  # ← añadido: una vez dispara, termina el turno


def get_priority(e, c):
    try:
        t = c.get_entity_type(e)
    except Exception:
        return 999

    if t == EntityType.HARVESTER:
        return 999
    if t in TORRETAS:
        return 2
    if t == EntityType.CORE:
        return 1
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