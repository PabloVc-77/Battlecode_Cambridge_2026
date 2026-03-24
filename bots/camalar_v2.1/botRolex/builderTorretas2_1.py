from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position, GameConstants
import math


############# MAIN #############

def run_builder_torretas(self, c: Controller):
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

################################


############# CONSTANTES AUXILIARES #############

# Rangos de visión y ataque por tipo de torreta (r²)
_TURRET_VISION_SQ = {
    EntityType.SENTINEL: GameConstants.SENTINEL_VISION_RADIUS_SQ,
    EntityType.BREACH: GameConstants.BREACH_VISION_RADIUS_SQ,
}
_TURRET_ATTACK_SQ = {
    EntityType.SENTINEL: 32,
    EntityType.BREACH:    5,
}

# Torretas enemigas que queremos priorizar como objetivo
_ENEMY_TURRETS = [EntityType.SENTINEL, EntityType.BREACH, EntityType.GUNNER]
 
# Máximo de torretas propias permitidas junto a un mismo harvester
_MAX_TORRETAS_POR_HARVESTER = 2
 
# Direcciones cardinales para buscar casillas adyacentes
_CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
_ALL_DIRS   = [
    Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
    Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST,
]

##################################################



############# METODOS AUXILIARES #############

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

def _sentinel_coverage(turret_pos: Position, direction: Direction, enemies: list[Position]) -> int:
    """
    Cuenta cuántos enemigos caen en la franja de ataque de una Sentinel.
    La Sentinel dispara en línea ±1 tile perpendicular a su dirección,
    dentro de attack r²=32. Solo acepta direcciones cardinales.
    """
    dx, dy = direction.delta()
 
    count = 0
    for ep in enemies:
        rel_x = ep.x - turret_pos.x
        rel_y = ep.y - turret_pos.y
 
        # Proyección sobre el eje de disparo (debe ser positiva → delante)
        proj_forward = rel_x * dx + rel_y * dy
        if proj_forward <= 0:
            continue
 
        # Distancia Chebyshev perpendicular a la línea de disparo
        perp_chebyshev = abs(rel_x * dy - rel_y * dx)
        if perp_chebyshev > 1:
            continue
 
        # Dentro del rango de ataque (r²)
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

def _supply_blocked(facing: Direction, supply_pos: Position, turret_pos: Position) -> bool:
    """
    Devuelve True si una torreta en turret_pos apuntando a `facing`
    no podría recibir suministro desde supply_pos.
    
    Las torretas diagonales pueden recibir desde los 4 lados → nunca bloqueadas.
    Las torretas cardinales no pueden recibir desde la dirección de su facing.
    
    La dirección "bloqueada" es exactamente `facing`: el tile en esa dirección
    desde la torreta es el que no puede alimentarla.
    """
    dx, dy = facing.delta()
    # Si es diagonal, puede recibir desde cualquier lado
    if dx != 0 and dy != 0:
        return False
    
    # Para cardinales: está bloqueada si supply_pos está en la dirección exacta de facing
    # (es decir, el supply tile es turret_pos + facing_delta * k para k > 0,
    #  y además está en la misma fila/columna según la dirección)
    rel_x = supply_pos.x - turret_pos.x
    rel_y = supply_pos.y - turret_pos.y
    
    # ¿El suministro está en la línea de facing?
    # NORTH (0,-1): misma columna, supply más arriba (rel_y < 0)
    # SOUTH (0, 1): misma columna, supply más abajo (rel_y > 0)
    # EAST  (1, 0): misma fila,    supply más a la derecha (rel_x > 0)
    # WEST  (-1,0): misma fila,    supply más a la izquierda (rel_x < 0)
    if dx == 0:  # NORTH o SOUTH
        return rel_x == 0 and (rel_y * dy > 0)
    else:        # EAST o WEST
        return rel_y == 0 and (rel_x * dx > 0)


def construir_torreta(self, c: Controller, p: Position, e: EntityType, supply_pos : Position) -> bool:
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
    buildings = c.get_nearby_buildings(min(vision_sq, GameConstants.BUILDER_BOT_VISION_RADIUS_SQ)) #evitar que de error
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
        # Las 7 direcciones válidas: todas excepto la de suministro
        candidates = [d for d in _ALL_DIRS if not _supply_blocked(d, supply_pos, p)]
        best_count = 0
        for d in candidates:
            count = _sentinel_coverage(p, d, enemy_turret_positions)
            if count > best_count:
                best_count = count
                best_dir = d

    elif e == EntityType.BREACH:
        # Las 7 direcciones válidas: todas excepto la de suministro
        candidates = [d for d in _ALL_DIRS if not _supply_blocked(d, supply_pos, p)]
        best_count = 0
        for d in candidates:
            count = _breach_coverage(p, d, enemy_turret_positions)
            if count > best_count:
                best_count = count
                best_dir = d

    # Si no hay torretas enemigas en rango (best_dir es None o best_count == 0),
    # Fallback: apuntar al core enemigo, verificando que no bloquea el suministro
    if best_dir is None and self.enemy_core_pos is not None:
        fallback = p.direction_to(self.enemy_core_pos)
        if not _supply_blocked(fallback, supply_pos, p):
            best_dir = fallback

    if best_dir is None:
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

def _contar_torretas_propias(c: Controller, harvester_pos: Position) -> int:
    """Cuenta cuántas Sentinels propias hay en las 8 casillas adyacentes al harvester."""
    count = 0
    for d in _ALL_DIRS:
        adj = harvester_pos.add(d)
        if not _is_in_bounds(c, adj) or not c.is_in_vision(adj):
            continue
        bid = c.get_tile_building_id(adj)
        if bid is not None and c.get_entity_type(bid) == EntityType.SENTINEL and c.get_team(bid) == c.get_team():
            count += 1
    return count
 
def _buscar_slot_para_torreta(c: Controller, harvester_pos: Position) -> Position | None:
    """
    Devuelve la primera casilla adyacente (cardinal) al harvester donde se
    podría colocar una Sentinel: debe estar en visión, vacía o con road propio,
    y no ser ore ni wall.
    Devuelve None si no hay hueco visible.
    """
    for d in _CARDINALS:
        adj = harvester_pos.add(d)
        if not _is_in_bounds(c, adj) or not c.is_in_vision(adj):
            continue
        env = c.get_tile_env(adj)
        if env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE):
            continue
        bid = c.get_tile_building_id(adj)
        if bid is None:
            return adj
        # Road propia: se puede destruir y construir encima
        if c.get_entity_type(bid) == EntityType.ROAD and c.get_team(bid) == c.get_team():
            return adj
    return None

# encontrar harvesters y poner 2 torretas adyacentes
def find_harvesters(self, c: Controller):
    buildings = c.get_nearby_buildings()
    for b in buildings:
        harvester_pos = c.get_position(b)
        # Aceptar harvesters de CUALQUIER equipo sobre titanio
        if c.get_entity_type(b) != EntityType.HARVESTER:
            continue
        if c.get_tile_env(harvester_pos) != Environment.ORE_TITANIUM:
            continue
        if harvester_pos in self.objetivos:
            continue
 
        # Solo añadir si aún hay hueco (menos de 2 torretas propias adyacentes)
        # y existe al menos una casilla visible donde construir
        torretas = _contar_torretas_propias(c, harvester_pos)
        if torretas >= _MAX_TORRETAS_POR_HARVESTER:
            continue
        slot = _buscar_slot_para_torreta(c, harvester_pos)
        if slot is None:
            continue
 
        self.objetivos.append(harvester_pos)
 
    # Eliminar harvesters que ya alcanzaron el límite o han desaparecido
    def harvester_completo(hpos):
        if not c.is_in_vision(hpos):
            return False  # no sabemos, conservar
        bid = c.get_tile_building_id(hpos)
        if bid is None or c.get_entity_type(bid) != EntityType.HARVESTER:
            return True  # ya no existe el harvester
        torretas = _contar_torretas_propias(c, hpos)
        slot = _buscar_slot_para_torreta(c, hpos)
        return torretas >= _MAX_TORRETAS_POR_HARVESTER or slot is None
 
    self.objetivos = [h for h in self.objetivos if not harvester_completo(h)]
 
    self.objetivos.sort(key=lambda hpos: (
        (hpos.x - c.get_position().x) ** 2 + (hpos.y - c.get_position().y) ** 2
    ))
 
    if not self.objetivos:
        dir = self.navegador.moveDvD(c, four_dirs=False)
        move_pos = c.get_position().add(dir)
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)
        return
 
    objetivo = self.objetivos[0]  # posición del harvester
 
    # Debug
    c.draw_indicator_line(c.get_position(), objetivo, 210, 0, 255)
    c.draw_indicator_line(c.get_position(), self.enemy_core_pos, 0, 220, 255)
 
    # Buscar el slot de construcción concreto
    slot = _buscar_slot_para_torreta(c, objetivo)
    if slot is None:
        # Sin hueco visible todavía: acercarse al harvester
        dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
        move_pos = c.get_position().add(dir)
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)
        return
 
    current = c.get_position()
    dist_to_slot = current.distance_squared(slot)
 
    if dist_to_slot <= 2:
        # Estamos junto al slot: destruir road si hace falta y construir
        bid_slot = c.get_tile_building_id(slot)
        if bid_slot is not None and c.get_entity_type(bid_slot) == EntityType.ROAD:
            if c.can_destroy(slot):
                c.destroy(slot)
        if construir_torreta(self, c, slot, EntityType.SENTINEL, objetivo):
            # Comprobar si este harvester ya está completo tras construir
            torretas = _contar_torretas_propias(c, objetivo)
            next_slot = _buscar_slot_para_torreta(c, objetivo)
            if torretas >= _MAX_TORRETAS_POR_HARVESTER or next_slot is None:
                if objetivo in self.objetivos:
                    self.objetivos.remove(objetivo)
            self.turrets_built += 1
    else:
        # Navegar hacia el slot
        dir = self.navegador.moveTo(c, slot, four_dirs=False)
        move_pos = current.add(dir)
        prev_pos = current
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(dir):
            c.move(dir)
 
        # Oportunidad de construir en prev_pos si está junto al slot
        if prev_pos.distance_squared(slot) <= 2:
            bid_slot = c.get_tile_building_id(slot)
            if bid_slot is not None and c.get_entity_type(bid_slot) == EntityType.ROAD:
                if c.can_destroy(slot):
                    c.destroy(slot)
            if construir_torreta(self, c, slot, EntityType.SENTINEL):
                torretas = _contar_torretas_propias(c, objetivo)
                next_slot = _buscar_slot_para_torreta(c, objetivo)
                if torretas >= _MAX_TORRETAS_POR_HARVESTER or next_slot is None:
                    if objetivo in self.objetivos:
                        self.objetivos.remove(objetivo)
                self.turrets_built += 1
 
# (sin usar actualmente)
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

##############################################