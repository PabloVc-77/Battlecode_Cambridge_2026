from cambc import Controller, Direction, EntityType, Environment, Position
import math

TORRETAS = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]

_ALL_DIRS = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST
]

def _get_enemy_priority_in_dir(pos: Position, direction: Direction, c: Controller) -> tuple[int, Position | None]:
    """
    Devuelve (mejor_prioridad, mejor_posición) enemiga en la línea de disparo
    si el gunner apuntase a `direction`. Ignora entidades aliadas.
    Retorna (1000, None) si no hay ninguna entidad enemiga relevante.
    """
    tiles = c.get_attackable_tiles_from(pos, direction, EntityType.GUNNER)
    best_priority = 1000
    best_pos = None

    for tile in tiles:
        # Comprobar building
        bid = c.get_tile_building_id(tile)
        if bid is not None:
            try:
                if c.get_entity_type(bid) == EntityType.BRIDGE and c.get_bridge_target(bid) == c.get_position():
                    continue # no disparar a un puente que nos da cobertura
                if c.get_entity_type(bid) == EntityType.CONVEYOR and c.get_conveyor_direction(bid) == direction.opposite():
                    continue # no disparar a una cinta transportadora que nos da cobertura
                if c.get_team(bid) != c.get_team():
                    p = get_priority_by_type(c.get_entity_type(bid))
                    if p < best_priority:
                        best_priority = p
                        best_pos = tile
            except Exception:
                pass

        # Comprobar builder bot
        bot_id = c.get_tile_builder_bot_id(tile)
        if bot_id is not None:
            try:
                if c.get_team(bot_id) != c.get_team():
                    p = get_priority_by_type(c.get_entity_type(bot_id))
                    if p < best_priority:
                        best_priority = p
                        best_pos = tile
            except Exception:
                pass

    return best_priority, best_pos


def run_gunner(self, c: Controller):
    my_pos = c.get_position()
    orientacion = c.get_direction()

    # Evaluar la dirección actual
    current_priority, current_best = _get_enemy_priority_in_dir(my_pos, orientacion, c)

    # Si no hay ningún enemigo en ninguna dirección, no hacer nada
    if current_priority == 1000:
        # Revisar si hay enemigos en otras direcciones antes de rendirse
        any_enemy = False
        for d in _ALL_DIRS:
            p, _ = _get_enemy_priority_in_dir(my_pos, d, c)
            if p < 1000:
                any_enemy = True
                break
        if not any_enemy:
            return

    # Buscar la dirección óptima entre todas las 8
    best_dir = orientacion
    best_priority = current_priority
    best_target = current_best

    for d in _ALL_DIRS:
        if d == orientacion:
            continue
        p, t = _get_enemy_priority_in_dir(my_pos, d, c)
        if p < best_priority:
            best_priority = p
            best_dir = d
            best_target = t

    if best_target is not None:
        c.draw_indicator_dot(best_target, 130, 130, 0)
    else:
        c.draw_indicator_dot(c.get_position(), 130, 130, 0)
    # Si la dirección óptima es distinta a la actual, rotar
    if best_dir != orientacion:
        if c.can_rotate(best_dir):
            c.rotate(best_dir)
        return  # Esperar a tener recursos o al siguiente turno tras rotar

    # Ya apuntamos en la dirección óptima: disparar
    target = c.get_gunner_target()
    if target is not None and c.can_fire(target):
        #comprobar que no es nuestra la casilla objetivo
        bid = c.get_tile_building_id(target)
        if bid is not None:
            if c.get_team(bid) == c.get_team() and c.get_entity_type(bid) != EntityType.ROAD:
                builder_id = c.get_tile_builder_bot_id(target)
                if builder_id is not None and c.get_team(builder_id) != c.get_team():
                    pass # si hay un builder bot enemigo, sí disparar aunque haya una construcción aliada
                else:
                    return # no disparar a nuestras propias construcciones (salvo carreteras)
        c.fire(target)


def get_priority_by_type(t: EntityType) -> int:
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
    if t == EntityType.MARKER:
        return 8
    if t == EntityType.HARVESTER:
        return 9
    return 1000