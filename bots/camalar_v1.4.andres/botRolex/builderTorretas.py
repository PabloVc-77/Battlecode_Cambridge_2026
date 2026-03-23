from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math

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
        find_harvesters(self, c)


def find_enemy_core(self, c: Controller):
    enemyC = self.enemy_core[self.simetry % 3]

    dir = self.navegador.moveTo(c, enemyC, False)
    move_pos = c.get_position().add(dir)
    if c.can_build_road(move_pos):
        c.build_road(move_pos)
    if c.can_move(dir):
        c.move(dir)

    if c.is_in_vision(enemyC):
        id = c.get_tile_building_id(enemyC)
        if c.get_entity_type(id) == EntityType.CORE:
            self.enemy_core_pos = enemyC
        else:
            self.simetry += 1

    buildings = c.get_nearby_buildings()
    for b in buildings:
        if c.get_entity_type(b) == EntityType.CORE and c.get_team(b) != c.get_team():
            self.enemy_core_pos = c.get_position(b)


def _get_adjacent_four(pos):
    """Devuelve las 4 casillas ortogonales adyacentes a una posición."""
    return [
        pos.add(Direction.NORTH),
        pos.add(Direction.SOUTH),
        pos.add(Direction.WEST),
        pos.add(Direction.EAST),
    ]

def _get_adjacent_eight(pos):
    """Devuelve las 8 casillas adyacentes (ortogonales + diagonales) a una posición."""
    return [
        pos.add(Direction.NORTH),
        pos.add(Direction.SOUTH),
        pos.add(Direction.WEST),
        pos.add(Direction.EAST),
        pos.add(Direction.NORTHEAST),
        pos.add(Direction.NORTHWEST),
        pos.add(Direction.SOUTHEAST),
        pos.add(Direction.SOUTHWEST),
    ]

def _choose_turret(self, c: Controller, build_pos, direction):
    """Construye Breach si ve el core enemigo, si no Sentinel. Devuelve True si construyó."""
    if c.is_in_vision(self.enemy_core_pos) and c.can_build_breach(build_pos, direction):
        c.build_breach(build_pos, direction)
        return True
    elif c.can_build_sentinel(build_pos, direction):
        c.build_sentinel(build_pos, direction)
        return True
    return False

def _get_building_at(c: Controller, pos):
    """Devuelve el building en una posición dada, o None si no hay ninguno."""
    for b in c.get_nearby_buildings():
        if c.get_position(b) == pos:
            return b
    return None

def _preparar_casilla_y_mover(self, c: Controller, adj):
    """
    Intenta preparar una casilla adyacente al harvester para poder entrar:
    - Si está vacía: construye road si puede, luego se mueve.
    - Si tiene un ROAD propio: lo destruye para poder entrar.
    Devuelve True si realizó alguna acción útil (move, build road, destroy).
    """
    my_pos = c.get_position()
    dir_to_adj = my_pos.direction_to(adj)

    if c.is_in_vision(adj) and c.is_tile_empty(adj):
        # Casilla vacía: necesita road para poder moverse
        if c.can_build_road(adj):
            c.build_road(adj)
            if c.can_move(dir_to_adj):
                c.move(dir_to_adj)
            return True
    else:
        building = _get_building_at(c, adj)   # ← sin self, no necesita estado
        if building is not None:
            if c.get_entity_type(building) == EntityType.ROAD:
                if c.can_destroy(adj):
                    c.destroy(adj)
                    return True
            return False  # otro edificio no road: bloqueado

    # Casilla transitable (road existente u otro): moverse directamente
    if c.can_move(dir_to_adj):
        c.move(dir_to_adj)
        return True

    return False

def _reset_estado(self):
    """Resetea la máquina de estados al estado inicial."""
    self.estado = "buscar"
    self.harvester_objetivo = None
    self.casilla_objetivo = None
    self.casilla_retroceso = None


def find_harvesters(self, c: Controller):

    # ── ESTADO: buscar ────────────────────────────────────────────────────────
    if self.estado == "buscar":
        buildings = c.get_nearby_buildings()
        for b in buildings:
            pos = c.get_position(b)
            if c.get_entity_type(b) == EntityType.HARVESTER and pos not in self.objetivos:
                self.objetivos.append(pos)

        self.objetivos.sort(key=lambda pos: math.sqrt(
            (pos.x - c.get_position().x) ** 2 + (pos.y - c.get_position().y) ** 2
        ))

        if not self.objetivos:
            dir = self.navegador.moveDvD(c, four_dirs=False)
            move_pos = c.get_position().add(dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        harvester_pos = self.objetivos[0]
        adyacentes = _get_adjacent_four(harvester_pos)   # ← sin self
        my_pos = c.get_position()

        # ── ¿Ya estamos en una casilla adyacente al harvester? ────────────
        for adj in adyacentes:
            if my_pos.x == adj.x and my_pos.y == adj.y:
                self.harvester_objetivo = harvester_pos
                self.casilla_objetivo = my_pos
                self.estado = "retroceder"
                break

        if self.estado != "retroceder":
            # ── Navegar hacia cualquier casilla adyacente al harvester ────
            adyacentes.sort(key=lambda pos: math.sqrt(
                (pos.x - my_pos.x) ** 2 + (pos.y - my_pos.y) ** 2
            ))

            accion_realizada = False
            for adj in adyacentes:
                resultado = _preparar_casilla_y_mover(self, c, adj)   # ← con self
                if resultado:
                    accion_realizada = True
                    break

            if not accion_realizada:
                self.objetivos.pop(0)
                dir = self.navegador.moveDvD(c, four_dirs=False)
                move_pos = c.get_position().add(dir)
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)
                if c.can_move(dir):
                    c.move(dir)
                return

    # ── ESTADO: retroceder ────────────────────────────────────────────────────
    if self.estado == "retroceder":
        my_pos = c.get_position()

        candidatos = _get_adjacent_eight(my_pos)   # ← sin self
        for retroceso in candidatos:
            if retroceso.x == self.harvester_objetivo.x and retroceso.y == self.harvester_objetivo.y:
                continue
            dist_harv = math.sqrt(
                (retroceso.x - self.harvester_objetivo.x) ** 2 +
                (retroceso.y - self.harvester_objetivo.y) ** 2
            )
            if dist_harv < 1.5:
                continue

            dir_retroceso = my_pos.direction_to(retroceso)
            if c.can_move(dir_retroceso):
                self.casilla_retroceso = retroceso
                c.move(dir_retroceso)
                self.estado = "construir"
                return

        return  # sin retroceso posible, esperar

    # ── ESTADO: construir ─────────────────────────────────────────────────────
    elif self.estado == "construir":
        my_pos = c.get_position()

        dist = math.sqrt(
            (my_pos.x - self.casilla_objetivo.x) ** 2 +
            (my_pos.y - self.casilla_objetivo.y) ** 2
        )
        if dist <= math.sqrt(2) + 0.01:
            direction = self.casilla_objetivo.direction_to(self.enemy_core_pos)
            if _choose_turret(self, c, self.casilla_objetivo, direction):   # ← con self
                self.objetivos.pop(0)
                _reset_estado(self)   # ← con self explícito
        else:
            _reset_estado(self)   # ← con self explícito