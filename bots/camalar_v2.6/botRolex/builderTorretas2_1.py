from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math

def run_builder_torretas2(self, c: Controller):
    if self.my_core is None:
        buildings = c.get_nearby_buildings()
        for b in buildings:
            if c.get_entity_type(b) == EntityType.CORE:
                self.my_core = c.get_position(b)

        w = c.get_map_width()
        h = c.get_map_height()

        x = self.my_core.x
        y = self.my_core.y

        self.enemy_core.append(Position(w - x, y))
        self.enemy_core.append(Position(x, h - y))
        self.enemy_core.append(Position(w - x, h - y))

    if self.enemy_core_pos is None:
        find_enemy_core(self, c)
    else:
        #if not find_connected_to_core(self, c): construir breach pegado al core, por hacer
        find_harvesters(self, c)


def find_enemy_core(self, c: Controller):
    enemyC = self.enemy_core[self.simetry % 3]

    # Debug: línea amarilla hacia el objetivo estimado del core enemigo
    c.draw_indicator_line(c.get_position(), enemyC, 255, 220, 0)

    dir = self.navegador.moveTo(c, enemyC, False)
    move_pos = c.get_position().add(dir)
    if c.can_build_road(move_pos):
        c.build_road(move_pos)
    if c.can_move(dir):
        c.move(dir)

    if c.is_in_vision(enemyC):
        id = c.get_tile_building_id(enemyC)
        if id is not None and c.get_entity_type(id) == EntityType.CORE and c.get_team(id) != c.get_team():
            self.enemy_core_pos = enemyC
        else:
            self.simetry += 1

    buildings = c.get_nearby_buildings()
    for b in buildings:
        if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
            self.enemy_core_pos = c.get_position(b)

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()

    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0


# Rangos de visión y ataque por tipo de torreta (r²)
_TURRET_VISION_SQ = {
    EntityType.SENTINEL: 32,
    EntityType.BREACH:   13,
}
_TURRET_ATTACK_SQ = {
    EntityType.SENTINEL: 32,
    EntityType.BREACH:    5,
}

# Torretas enemigas que queremos priorizar como objetivo
_ENEMY_TURRETS = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]


def _sentinel_coverage(turret_pos: Position, direction: Direction, enemies: list[Position]) -> int:
    """
    Cuenta cuántos enemigos caen en la franja de ataque de una Sentinel.
    La Sentinel dispara en línea ±1 tile perpendicular a su dirección,
    dentro de attack r²=32. Solo acepta direcciones cardinales.
    """
    dx, dy = direction.delta()
    # Vector perpendicular a la dirección de disparo
    perp_x, perp_y = dy, dx  # rotar 90°

    count = 0
    for ep in enemies:
        rel_x = ep.x - turret_pos.x
        rel_y = ep.y - turret_pos.y

        # Proyección sobre el eje de disparo (debe ser positiva → delante)
        proj_forward = rel_x * dx + rel_y * dy
        if proj_forward <= 0:
            continue

        # Proyección sobre el eje perpendicular (debe estar dentro de ±1)
        proj_perp = abs(rel_x * perp_x + rel_y * perp_y)
        if proj_perp > 1:
            continue

        # Dentro del rango de ataque
        if rel_x * rel_x + rel_y * rel_y <= _TURRET_ATTACK_SQ[EntityType.SENTINEL]:
            count += 1

    return count


def _breach_coverage(turret_pos: Position, direction: Direction, enemies: list[Position]) -> int:
    """
    Cuenta cuántos enemigos caen en el cono 180° de una Breach.
    El cono cubre todo el semiplano delantero dentro de attack r²=5.
    Acepta las 8 direcciones.
    """
    dx, dy = direction.delta()
    count = 0
    for ep in enemies:
        rel_x = ep.x - turret_pos.x
        rel_y = ep.y - turret_pos.y

        dist_sq = rel_x * rel_x + rel_y * rel_y
        if dist_sq == 0 or dist_sq > _TURRET_ATTACK_SQ[EntityType.BREACH]:
            continue

        # Producto escalar positivo → en el semiplano delantero
        if rel_x * dx + rel_y * dy > 0:
            count += 1

    return count


def construir_torreta(self, c: Controller, p: Position, e: EntityType) -> bool:
    """
    Construye una torreta de tipo `e` en la posición `p` eligiendo la dirección
    que maximice la cobertura sobre torretas enemigas visibles.

    Prioridad:
      1. Dirección que apunte a la mayor cantidad de torretas enemigas en rango.
      2. Si no hay torretas enemigas visibles, apuntar al core enemigo.
      3. Fallback: apuntar al core enemigo igualmente.

    Devuelve True si construyó la torreta, False en caso contrario.
    """
    if e not in (EntityType.SENTINEL, EntityType.BREACH):
        return False

    vision_sq = _TURRET_VISION_SQ[e]

    # Recoger edificios enemigos visibles dentro del rango de visión de la torreta
    enemy_turret_positions = []
    buildings = c.get_nearby_buildings(vision_sq)
    for b in buildings:
        try:
            if c.get_team(b) == c.get_team():
                continue
            if c.get_entity_type(b) in _ENEMY_TURRETS:
                enemy_turret_positions.append(c.get_position(b))
        except Exception:
            continue

    best_dir = None

    if e == EntityType.SENTINEL:
        # Solo direcciones cardinales tienen sentido para la franja ±1
        candidates = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
        best_count = 0
        for d in candidates:
            count = _sentinel_coverage(p, d, enemy_turret_positions)
            if count > best_count:
                best_count = count
                best_dir = d

    elif e == EntityType.BREACH:
        # Las 8 direcciones son válidas para el cono 180°
        candidates = [
            Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
            Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
        ]
        best_count = 0
        for d in candidates:
            count = _breach_coverage(p, d, enemy_turret_positions)
            if count > best_count:
                best_count = count
                best_dir = d

    # Si no hay torretas enemigas en rango (best_dir es None o best_count == 0),
    # apuntar al core enemigo como fallback
    if best_dir is None and self.enemy_core_pos is not None:
        best_dir = p.direction_to(self.enemy_core_pos)
    elif best_dir is None:
        # Último recurso: sin información, no construimos
        return False

    # Construir la torreta según su tipo
    if e == EntityType.SENTINEL:
        if c.can_build_sentinel(p, best_dir):
            c.build_sentinel(p, best_dir)
            return True
    elif e == EntityType.BREACH:
        if c.can_build_breach(p, best_dir):
            c.build_breach(p, best_dir)
            return True

    return False

def find_harvesters(self, c: Controller):
    buildings = c.get_nearby_buildings()
    for b in buildings:
        pos = c.get_position(b)
        if c.get_entity_type(b) == EntityType.HARVESTER and pos not in self.objetivos and c.get_team(b) != c.get_team():
            #si el harvester no es de titanium no lo tenemos en cuenta
            if c.get_tile_env(pos) != Environment.ORE_TITANIUM:
                continue
            #mirar si ya hay torretas nuestras alrededor de este harvester
            hay_torreta = False
            for dir in Direction:
                pos_torreta = pos.add(dir)
                if _is_in_bounds(c, pos_torreta) and c.is_in_vision(pos_torreta):
                    id = c.get_tile_building_id(pos_torreta)
                    if c.get_entity_type(id) == EntityType.SENTINEL and c.get_team(id) == c.get_team():
                        hay_torreta = True
                        break
            if not hay_torreta:
                self.objetivos.append(pos)
    

    self.objetivos.sort(key=lambda pos: math.sqrt(
        (pos.x - c.get_position().x) ** 2 + (pos.y - c.get_position().y) ** 2
    ))

    if not self.objetivos:
        dir = self.navegador.moveExplore(c, four_dirs=False)
        move_pos = c.get_position().add(dir)
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)
        return

    #tenemos objetivos, vamos al más cercano
    objetivo = self.objetivos[0]
    
    moveNext = True

    dist_to = math.sqrt((objetivo.x - c.get_position().x) ** 2 + (objetivo.y - c.get_position().y) ** 2)
    if dist_to <= 1:
        tile = c.get_tile_building_id(c.get_position())
        team = c.get_team(tile)
        moveNext = False
        if team != c.get_team():
            #romper esta casilla
            if c.can_fire(c.get_position()):
                c.fire(c.get_position())
        else:
            #quitar esta casilla
            if c.can_destroy(c.get_position()):
                c.destroy(c.get_position())
        if c.get_tile_building_id(c.get_position()) == None:
            moveNext = True


    # Debug: línea morada hacia el harvester objetivo
    c.draw_indicator_line(c.get_position(), objetivo, 210, 0, 255)
    # Debug: línea cyan hacia el core enemigo (una vez conocido)
    c.draw_indicator_line(c.get_position(), self.enemy_core_pos, 0, 220, 255)
    if moveNext:
        dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
        move_pos = c.get_position().add(dir)
        prev_pos = c.get_position()
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)

        #intentar construir torreta en la casilla anterior
        if construir_torreta(self, c, prev_pos, EntityType.SENTINEL):
            self.objetivos.pop(0)  # eliminar este objetivo de la lista
            self.turrets_built += 1


def find_connected_to_core(self, c: Controller):
    DISTANCIA_MAX_AL_CORE_SQ = 25
    my_pos = c.get_position()

    # ── Si hay una casilla pendiente de construcción, intentar construir ──
    if self.breach_objetivo_pendiente is not None:
        objetivo = self.breach_objetivo_pendiente
        dist_sq = (objetivo.x - my_pos.x) ** 2 + (objetivo.y - my_pos.y) ** 2

        # Comprobar si el enemigo reconstruyó algo en esa casilla
        tile_id = c.get_tile_building_id(objetivo)
        if tile_id is not None and c.get_team(tile_id) != c.get_team():
            # El enemigo reconstruyó: volver a moverse encima para romper
            if dist_sq == 0:
                if c.can_fire(my_pos):
                    c.fire(my_pos)
            else:
                dir_to = my_pos.direction_to(objetivo)
                if c.can_move(dir_to):
                    c.move(dir_to)
            return True

        # Destruir road propio si lo pusimos nosotros sin querer
        if tile_id is not None and c.get_team(tile_id) == c.get_team():
            if c.can_destroy(objetivo):
                c.destroy(objetivo)
            return True

        # Casilla libre: asegurarse de estar adyacente y construir
        if dist_sq <= 2 and dist_sq > 0:
            direction = objetivo.direction_to(self.enemy_core_pos)
            if c.can_build_breach(objetivo, direction):
                c.build_breach(objetivo, direction)
                self.breach_objetivo_pendiente = None
                if objetivo in self.caminos_objetivo:
                    self.caminos_objetivo.remove(objetivo)
                self.turrets_built += 1
            # Si no puede aún (cooldown/recursos), esperar en este mismo turno
            return True

        if dist_sq == 0:
            # Estamos encima: salir para poder construir
            for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
                      Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST]:
                retroceso = my_pos.add(d)
                dir_r = my_pos.direction_to(retroceso)
                if c.can_move(dir_r):
                    c.move(dir_r)
                    return True

        # Lejos de la casilla pendiente: volver a acercarse
        dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
        move_pos = my_pos.add(dir)
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)
        return True

    # ── Buscar nuevos objetivos ───────────────────────────────────────────
    buildings = c.get_nearby_buildings()
    for b in buildings:
        pos = c.get_position(b)
        tipo = c.get_entity_type(b)

        if tipo not in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE]:
            continue
        if c.get_team(b) == c.get_team():
            continue
        if pos in self.caminos_objetivo:
            continue

        dist_sq = (pos.x - self.enemy_core_pos.x) ** 2 + (pos.y - self.enemy_core_pos.y) ** 2
        if dist_sq > DISTANCIA_MAX_AL_CORE_SQ:
            continue

        id_en_pos = c.get_tile_building_id(pos)
        if id_en_pos is not None and c.get_entity_type(id_en_pos) == EntityType.BREACH and c.get_team(id_en_pos) == c.get_team():
            continue

        self.caminos_objetivo.append(pos)

    # Limpiar objetivos ya resueltos
    def objetivo_resuelto(pos):
        if not c.is_in_vision(pos):
            return False
        id_en_pos = c.get_tile_building_id(pos)
        if id_en_pos is None:
            return False  # libre pero sin breach aún, no descartar
        tipo = c.get_entity_type(id_en_pos)
        if tipo == EntityType.BREACH and c.get_team(id_en_pos) == c.get_team():
            return True
        if c.get_team(id_en_pos) == c.get_team():
            return True
        return False

    self.caminos_objetivo = [p for p in self.caminos_objetivo if not objetivo_resuelto(p)]
    self.caminos_objetivo.sort(key=lambda p: (
        (p.x - my_pos.x) ** 2 + (p.y - my_pos.y) ** 2
    ))

    if not self.caminos_objetivo:
        return False

    objetivo = self.caminos_objetivo[0]
    c.draw_indicator_line(my_pos, objetivo, 210, 150, 0)
    dist_sq_to = (objetivo.x - my_pos.x) ** 2 + (objetivo.y - my_pos.y) ** 2

    # ── Estamos EN la casilla objetivo ────────────────────────────────────
    if dist_sq_to == 0:
        tile_id = c.get_tile_building_id(my_pos)
        if tile_id is not None and c.get_team(tile_id) != c.get_team():
            if c.can_fire(my_pos):
                c.fire(my_pos)
            return True
        if tile_id is not None and c.get_team(tile_id) == c.get_team():
            if c.can_destroy(my_pos):
                c.destroy(my_pos)
            return True

        # Casilla libre: salir y marcar como pendiente
        for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST,
                  Direction.NORTHEAST, Direction.NORTHWEST, Direction.SOUTHEAST, Direction.SOUTHWEST]:
            retroceso = my_pos.add(d)
            dir_r = my_pos.direction_to(retroceso)
            if c.can_move(dir_r):
                c.move(dir_r)
                self.breach_objetivo_pendiente = objetivo  # ← guardar para construir
                return True
        return True

    # ── Estamos adyacentes ────────────────────────────────────────────────
    if dist_sq_to <= 2:
        tile_id = c.get_tile_building_id(objetivo)
        if tile_id is not None and c.get_team(tile_id) != c.get_team():
            dir_to = my_pos.direction_to(objetivo)
            if c.can_move(dir_to):
                c.move(dir_to)
            return True
        if tile_id is not None and c.get_team(tile_id) == c.get_team():
            if c.can_destroy(objetivo):
                c.destroy(objetivo)
            return True

        # Casilla libre: intentar construir o marcar pendiente
        direction = objetivo.direction_to(self.enemy_core_pos)
        if c.can_build_breach(objetivo, direction):
            c.build_breach(objetivo, direction)
            self.caminos_objetivo.remove(objetivo)
            self.breach_built += 1
        else:
            # No puede construir aún: marcar pendiente y esperar aquí
            self.breach_objetivo_pendiente = objetivo
        return True

    # ── Lejos: navegar ────────────────────────────────────────────────────
    dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
    move_pos = my_pos.add(dir)
    if c.can_build_road(move_pos):
        c.build_road(move_pos)
    if c.can_move(dir):
        c.move(dir)
    return True