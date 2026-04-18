from cambc import Controller, Direction, EntityType, Environment, Position, ResourceType


def _is_in_bounds(c: Controller, pos: Position) -> bool:
    # Kept for backward compatibility; use self._in_bounds() inside the class.
    w = c.get_map_width()
    h = c.get_map_height()
    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

class Movement:
    def __init__(self):
        self.pending_removed_barriers: list[tuple[Position, bool]] = []
        pass

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        if direction == Direction.CENTRE:
            return False
        dest = c.get_position().add(direction)
        if not _is_in_bounds(c, dest):
            return False

        current = c.get_position()

        # Reconstruir barriers
        still_pending = []
        for p, road_built in self.pending_removed_barriers:
            if p == current:
                still_pending.append((p, road_built))
                continue
            if not c.is_in_vision(p):
                still_pending.append((p, road_built))
                continue

            bid = c.get_tile_building_id(p)

            if not road_built:
                # Aún no se construyó la road — intentarlo ahora
                if c.can_build_road(p):
                    c.build_road(p)
                    still_pending.append((p, True))
                else:
                    still_pending.append((p, False))
                continue

            # Road ya construida: esperar a que el bot salga y reconstruir barrier
            if bid is not None and c.get_entity_type(bid) != EntityType.ROAD:
                continue  # alguien construyó encima, descartar
            if bid is not None:
                if not c.can_destroy(p):
                    still_pending.append((p, True))
                    continue
                c.destroy(p)
            if c.can_build_barrier(p):
                c.build_barrier(p)
            else:
                still_pending.append((p, True))
        self.pending_removed_barriers = still_pending

        # Gestionar barrier en el destino
        bid = c.get_tile_building_id(dest)
        if bid is not None:
            et = c.get_entity_type(bid)
            if et == EntityType.BARRIER and c.get_team() == c.get_team(bid):
                if c.can_destroy(dest):
                    c.destroy(dest)
                    self.pending_removed_barriers.append((dest, False))
                else:
                    return False

        if c.can_build_road(dest):
            c.build_road(dest)
            # Actualizar la entrada recién añadida a road_built=True
            if self.pending_removed_barriers and self.pending_removed_barriers[-1][0] == dest:
                self.pending_removed_barriers[-1] = (dest, True)
        if c.can_move(direction):
            c.move(direction)
            return True
        return False