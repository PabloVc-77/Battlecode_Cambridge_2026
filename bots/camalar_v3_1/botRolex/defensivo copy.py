from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position, ResourceType
import math
import bignav_a_mem as bugnav

#get_tile_env(pos: Position) == None

def _is_diagonal(d: Direction) -> bool:
    dx, dy = d.delta()
    return dx != 0 and dy != 0

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

def _conveyor_dir_to_core(tile: Position, core_pos: Position) -> Direction:
    dx = core_pos.x - tile.x
    dy = core_pos.y - tile.y
    if dx == 0 and dy == 0:
        return Direction.CENTRE
    if abs(dx) >= abs(dy):
        return Direction.EAST if dx > 0 else Direction.WEST
    else:
        return Direction.SOUTH if dy > 0 else Direction.NORTH

def is_there_axionite(c: Controller, centro: Position):
    cx = centro.x
    cy = centro.y
    casillas_validas = []
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if max(abs(dx), abs(dy)) == 2:
                pos = Position(cx + dx, cy + dy)
                if c.is_in_vision(pos) and _is_in_bounds(c, pos):
                    conveyor = c.get_tile_building_id(pos)
                    if conveyor is not None and c.get_entity_type(conveyor) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR]:
                        material = c.get_stored_resource(conveyor)
                        if material is not None and material.name == "RAW_AXIONITE":
                            casillas_validas.append(pos)
    return casillas_validas


# ─────────────────────────────────────────────────────────
#  Estructura de datos para rastrear cada conveyor del anillo
# ─────────────────────────────────────────────────────────
class ConveyorRecord:
    """Guarda el estado conocido de una casilla del anillo de conveyors."""
    def __init__(self, pos: Position, direction: Direction):
        self.pos = pos
        self.direction = direction          # dirección hacia el core
        self.seen_titanium: bool = False    # flag: alguna vez tuvo titanio
        self.is_armoured: bool = False      # ya es armoured conveyor


class Defensivo:
    def __init__(self, ct: Controller):
        self.objetivos = []
        self.spawn = None

        # Builder_Defensivo Vars
        self.my_core = None
        self.furnace = False
        self.splitter_pos = None
        self.furnace_pos = None
        self.fase2 = 0
        self.replace = []

        self.navegador = bugnav.BugNav()

        # ── Nuevo: registro de conveyors del anillo ──────────────
        # dict[Position, ConveyorRecord]
        self.ring_conveyors: dict = {}

        builds = ct.get_nearby_buildings()
        for b in builds:
            if ct.get_entity_type(b) == EntityType.CORE:
                self.spawn = ct.get_position(b)
                break

    def _clear_tile(self, c: Controller, target: Position) -> bool:
        """
        Intenta eliminar lo que haya en `target`.
        - Aliado: c.destroy() si estamos a distancia² <= 2.
        - Enemigo: c.fire() solo si estamos encima (distancia² == 0).

        Devuelve True si el tile ya está despejado (no hay nada),
        False si aún queda algo (o no podemos actuar todavía).
        En caso de que necesitemos acercarnos, hace el movimiento.
        """
        building_id = c.get_tile_building_id(target)
        if building_id is None:
            return True  # ya está libre

        current = c.get_position()
        is_ally = c.get_team(building_id) == c.get_team()

        if is_ally:
            if c.can_destroy(target):
                c.destroy(target)
                return True
            # Nos acercamos para poder destruirlo (necesita dist² <= 2)
            dir = self.navegador.moveTo(c, target, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return False
        else:
            # Enemigo: necesitamos estar encima
            if current == target:
                if c.can_fire(target):
                    c.fire(target)
                    return c.get_tile_building_id(target) is None
                return False
            else:
                # Movernos encima si es posible
                if c.is_tile_passable(target):
                    dir = self.navegador.moveTo(c, target, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    if c.can_move(dir):
                        c.move(dir)
                return False

    # ──────────────────────────────────────────────────────────────
    #  Actualiza los registros del anillo y detecta titanio
    # ──────────────────────────────────────────────────────────────
    def _update_ring_records(self, c: Controller, node_pos: Position):
        """
        Recorre las 12 casillas cardinales del anillo (dist máx = 2, sin diagonales).
        Actualiza seen_titanium, is_armoured, y detecta casillas que hay que reparar.
        Devuelve (repair_priority, repair_normal) — listas de pos a reparar/reconstruir,
        ordenadas: primero las que han visto titanio.
        """
        cx, cy = node_pos.x, node_pos.y
        repair_titanium: list = []   # rotas que habían visto titanio
        repair_normal: list = []     # rotas sin haber visto titanio

        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if max(abs(dx), abs(dy)) == 2 and abs(dx) != abs(dy):
                    pos = Position(cx + dx, cy + dy)
                    if not _is_in_bounds(c, pos) or not c.is_in_vision(pos):
                        continue

                    cdir = _conveyor_dir_to_core(pos, node_pos)
                    building_id = c.get_tile_building_id(pos)
                    env = c.get_tile_env(pos)

                    # ── Inicializar registro si no existe ──────────────
                    if pos not in self.ring_conveyors:
                        self.ring_conveyors[pos] = ConveyorRecord(pos, cdir)

                    rec: ConveyorRecord = self.ring_conveyors[pos]

                    if building_id is not None:
                        btype = c.get_entity_type(building_id)
                        bteam = c.get_team(building_id)

                        if btype in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                            if bteam == c.get_team():
                                # Actualizar flag de titanio
                                try:
                                    mat = c.get_stored_resource(building_id)
                                    if mat == ResourceType.TITANIUM:
                                        rec.seen_titanium = True
                                except Exception:
                                    pass

                                # Actualizar si ya es armoured
                                rec.is_armoured = (btype == EntityType.ARMOURED_CONVEYOR)
                            else:
                                # Conveyor enemigo — tratar como rota
                                if rec.seen_titanium:
                                    repair_titanium.append(pos)
                                else:
                                    repair_normal.append(pos)
                        elif pos != self.splitter_pos and pos != self.furnace_pos:
                            # Hay algo que NO es conveyor aliado (road, barrier, etc.)
                            # → hay que reparar
                            if rec.seen_titanium:
                                repair_titanium.append(pos)
                            else:
                                repair_normal.append(pos)
                    else:
                        # Casilla vacía donde debería haber conveyor
                        if pos in self.ring_conveyors and pos != self.splitter_pos and pos != self.furnace_pos:
                            if rec.seen_titanium:
                                repair_titanium.append(pos)
                            else:
                                repair_normal.append(pos)

        return repair_titanium, repair_normal

    # ──────────────────────────────────────────────────────────────
    #  Tarea de mantenimiento del anillo
    # ──────────────────────────────────────────────────────────────
    def _maintain_ring(self, c: Controller, node_pos: Position) -> bool:
        """
        Cura conveyors dañados, repara casillas rotas y sube a armoured cuando puede.
        Devuelve True si consumió cooldown de acción (para que el caller no actúe más).
        """
        acted = False
        current = c.get_position()
        cx, cy = node_pos.x, node_pos.y

        repair_titanium, repair_normal = self._update_ring_records(c, node_pos)
        repair_all = repair_titanium + repair_normal   # prioridad: titanio primero

        # ── 1. Curar conveyors aliados dañados (por orden de prioridad) ───
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if max(abs(dx), abs(dy)) == 2 and abs(dx) != abs(dy):
                    pos = Position(cx + dx, cy + dy)
                    if not _is_in_bounds(c, pos) or not c.is_in_vision(pos):
                        continue
                    building_id = c.get_tile_building_id(pos)
                    if building_id is None:
                        continue
                    btype = c.get_entity_type(building_id)
                    if btype not in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                        continue
                    if c.get_team(building_id) != c.get_team():
                        continue
                    if c.get_hp(building_id) < c.get_max_hp(building_id):
                        rec = self.ring_conveyors.get(pos)
                        # Prioridad: si ha visto titanio, ir primero
                        priority = rec.seen_titanium if rec else False
                        if c.can_heal(pos):
                            c.heal(pos)
                            acted = True
                            break
                        else:
                            # Acercarnos
                            d = current.direction_to(pos)
                            if c.can_move(d):
                                c.move(d)
                            return acted
            if acted:
                break

        # ── 2. Reparar casillas rotas (prioridad: seen_titanium primero) ──
        if not acted and repair_all:
            target_pos = repair_all[0]
            rec: ConveyorRecord = self.ring_conveyors.get(target_pos)
            cdir = rec.direction if rec else _conveyor_dir_to_core(target_pos, node_pos)

            building_id = c.get_tile_building_id(target_pos)
            if building_id is not None:
                btype = c.get_entity_type(building_id)
                bteam = c.get_team(building_id)
                # Destruir lo que sea que esté ahí (enemigo o estructura incorrecta)
                if c.can_destroy(target_pos):
                    c.destroy(target_pos)
                elif c.can_fire(target_pos):
                    c.fire(target_pos)
                    acted = True
                else:
                    d = current.direction_to(target_pos)
                    if c.can_move(d):
                        c.move(d)
                    return acted
            
            # Construir: preferir armoured si ha visto titanio o si podemos permitírnoslo
            if c.get_tile_building_id(target_pos) is None:
                if c.can_build_armoured_conveyor(target_pos, cdir):
                    c.build_armoured_conveyor(target_pos, cdir)
                    if rec:
                        rec.is_armoured = True
                    acted = True
                elif c.can_build_conveyor(target_pos, cdir):
                    c.build_conveyor(target_pos, cdir)
                    acted = True
                else:
                    d = current.direction_to(target_pos)
                    if c.can_move(d):
                        c.move(d)

        # ── 3. Mejorar conveyors normales a armoured ─
        if not acted:
            for pos, rec in self.ring_conveyors.items():
                if not rec.is_armoured:
                    if not c.is_in_vision(pos):
                        continue
                    building_id = c.get_tile_building_id(pos)
                    if building_id is None:
                        continue
                    if c.get_entity_type(building_id) != EntityType.CONVEYOR:
                        continue
                    if c.get_team(building_id) != c.get_team():
                        continue
                    cdir = rec.direction
                    if c.can_destroy(pos) and c.can_build_armoured_conveyor(pos, cdir):
                        # Solo destruir si podemos construir inmediatamente (misma casilla)
                        # y tenemos recursos
                        ti, ax = c.get_global_resources()
                        ac_cost = c.get_armoured_conveyor_cost()
                        if ti >= ac_cost[0] and ax >= ac_cost[1]:
                            if c.can_destroy(pos):
                                c.destroy(pos)
                            # La construcción se hará el siguiente turno al detectar la casilla vacía
                            if c.can_build_armoured_conveyor(pos, cdir):
                                c.build_armoured_conveyor(pos, cdir)
                            break
                    elif c.can_build_armoured_conveyor(pos, cdir):
                        # La conveyor ya no existe; construir armoured
                        c.build_armoured_conveyor(pos, cdir)
                        rec.is_armoured = True
                        acted = True
                        break

        return acted

    # ──────────────────────────────────────────────────────────────
    #  run
    # ──────────────────────────────────────────────────────────────
    def run(self, c: Controller):

        if self.my_core is None:
            casillas = c.get_nearby_buildings()
            for nodeID in casillas:
                if c.get_entity_type(nodeID) == EntityType.CORE:
                    self.my_core = nodeID
                    break

        if self.my_core is None:
            return

        nodePosition = c.get_position(self.my_core)

        # Curar el core si está dañado
        if c.get_hp(self.my_core) < c.get_max_hp(self.my_core) and c.can_heal(nodePosition):
            c.heal(nodePosition)

        current = c.get_position()

        # Curar nuestra propia casilla si hay algo dañado
        if c.can_heal(current):
            c.heal(current)

        direc = current.direction_to(nodePosition)

        # AXIONITE MISSION
        entradas = is_there_axionite(c, nodePosition)
        if (len(entradas) > 0 or self.furnace) and self.fase2 is not None:
            self.furnace = True
            if self.splitter_pos is None:
                self.splitter_pos = entradas[0]
            self.mision_axionite(c, nodePosition)
            if (self.fase2 is not None and self.fase2 < 2 and c.get_global_resources()[0] >= c.get_splitter_cost()[0] + 15) or \
               c.get_global_resources()[0] >= c.get_foundry_cost()[0] - 20:
                return

        # ── Mantenimiento del anillo (curar + reparar + mejorar) ──
        self._maintain_ring(c, nodePosition)

        # ── Construcción normal del anillo ─────────────────────────
        circulo = self.obtener_anillo_16_casillas(c, nodePosition)
        obj = circulo[0] if circulo else None

        if obj is not None:
            c.draw_indicator_dot(obj, 186, 227, 0)
            cdir = _conveyor_dir_to_core(obj, nodePosition)

            if c.can_destroy(obj):
                c.destroy(obj)
            elif c.can_fire(obj):
                c.fire(obj)

            if c.can_build_armoured_conveyor(obj, cdir):
                c.build_armoured_conveyor(obj, cdir)
                rec = self.ring_conveyors.get(obj)
                if rec:
                    rec.is_armoured = True
            elif c.can_build_conveyor(obj, cdir):
                c.build_conveyor(obj, cdir)
            else:
                direc = current.direction_to(obj)

        if c.can_move(direc):
            c.move(direc)

    def obtener_anillo_16_casillas(self, c: Controller, centro: Position):
        cx = centro.x
        cy = centro.y
        casillas_validas = []

        furnace = None
        if self.furnace_pos is not None:
            furnace = c.get_tile_builder_bot_id(self.furnace_pos)

        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if max(abs(dx), abs(dy)) == 2 and abs(dx) != abs(dy):
                    pos = Position(cx + dx, cy + dy)
                    if _is_in_bounds(c, pos) and c.is_in_vision(pos):
                        something = c.get_tile_building_id(pos)
                        if c.is_tile_empty(pos) or (something is not None and c.get_entity_type(something) in (EntityType.MARKER, EntityType.ROAD)):
                            if something is not None and c.get_entity_type(something) == EntityType.ROAD and c.get_team(something) != c.get_team():
                                continue
                            casillas_validas.append(pos)
                        elif self.furnace_pos is not None and c.is_in_vision(self.furnace_pos) and \
                             furnace is not None and c.get_entity_type(furnace) == EntityType.FOUNDRY and \
                             something is not None and c.get_entity_type(something) in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
                            dir_conv = c.get_direction(something)
                            if not _is_diagonal(dir_conv) and dir_conv != pos.direction_to(self.furnace_pos):
                                casillas_validas.append(pos)

        casillas_validas.sort(key=lambda p: centro.distance_squared(p))

        for w in casillas_validas:
            c.draw_indicator_dot(w, 245, 39, 204)

        return casillas_validas

    def mision_axionite(self, c: Controller, nodePosition: Position):
        splitter_pos = self.splitter_pos
        if self.furnace_pos is None:
            viable_places = [splitter_pos.add(Direction.NORTH), splitter_pos.add(Direction.EAST),
                             splitter_pos.add(Direction.SOUTH), splitter_pos.add(Direction.WEST)]
            true_viable_places = []
            for vp in viable_places:
                if _is_in_bounds(c, vp) and vp.distance_squared(nodePosition) <= 7 and vp.distance_squared(nodePosition) >= 4:
                    c.draw_indicator_dot(vp, 245, 73, 39)
                    true_viable_places.append(vp)

            if len(true_viable_places) == 0:
                self.furnace = False
                return

            self.furnace_pos = true_viable_places[0]

        furnace_pos = self.furnace_pos
        current = c.get_position()

        c.draw_indicator_dot(splitter_pos, 255, 255, 255)
        c.draw_indicator_dot(furnace_pos, 0, 0, 0)

        splitter_dir = splitter_pos.direction_to(nodePosition)
        if _is_diagonal(splitter_dir):
            splitter_dir = splitter_dir.rotate_left()

        b_id_at_split = None

        if c.is_in_vision(splitter_pos):
            b_id_at_split = c.get_tile_building_id(splitter_pos)
        else:
            dir = current.direction_to(splitter_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        if b_id_at_split is not None and c.get_entity_type(b_id_at_split) != EntityType.SPLITTER:
            if c.can_destroy(splitter_pos):
                if c.get_global_resources()[0] > c.get_splitter_cost()[0] and c.get_action_cooldown() == 0:
                    c.destroy(splitter_pos)
            else:
                direc = current.direction_to(splitter_pos)
                if c.can_move(direc):
                    c.move(direc)

        b_id_at_split = c.get_tile_building_id(splitter_pos)

        if b_id_at_split is None:
            if len(self.replace) == 0:
                self.check_surrounding_conveyors(c, splitter_pos, splitter_dir)
            if c.can_build_splitter(splitter_pos, splitter_dir):
                c.build_splitter(splitter_pos, splitter_dir)
                self.fase2 += 1

        if self.fase2 == 1:
            if len(self.replace) == 0:
                self.fase2 += 1
            else:
                r = self.replace[0]
                if c.can_destroy(r) and c.get_global_resources()[0] > c.get_bridge_cost()[0] and c.get_action_cooldown() == 0:
                    c.destroy(r)
                else:
                    build = c.get_tile_building_id(r)
                    if build is not None and c.get_team(build) != c.get_team():
                        self.replace.pop()
                    else:
                        dir = self.navegador.moveTo(c, r, False)
                        if c.can_move(dir):
                            c.move(dir)

                if c.can_build_bridge(r, splitter_pos):
                    c.build_bridge(r, splitter_pos)
                    self.replace.pop()

        current = c.get_position()
        if c.is_in_vision(furnace_pos):
            b_id_at_furnace = c.get_tile_building_id(furnace_pos)
        else:
            dir = current.direction_to(furnace_pos)
            if c.can_move(dir):
                c.move(dir)
            return

        if self.fase2 == 2 and c.get_global_resources()[0] >= c.get_foundry_cost()[0]:
            if b_id_at_furnace is not None and c.get_entity_type(b_id_at_furnace) != EntityType.FOUNDRY:
                if c.can_destroy(furnace_pos):
                    c.destroy(furnace_pos)
                else:
                    direc = current.direction_to(furnace_pos)
                    if c.can_move(direc):
                        c.move(direc)
            elif b_id_at_furnace is None:
                if c.can_build_foundry(furnace_pos):
                    c.build_foundry(furnace_pos)
                    self.fase2 = None
                    self.furnace = False

    def check_surrounding_conveyors(self, c: Controller, split_pos: Position, split_dir: Direction):
        dirs = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
        adj = []
        for d in dirs:
            p = split_pos.add(d)
            if not _is_in_bounds(c, p) or p == self.furnace_pos:
                continue
            if c.is_in_vision(p):
                conveyor = c.get_tile_building_id(p)
            else:
                dir = c.get_position().direction_to(p)
                if c.can_move(dir):
                    c.move(dir)
                return
            if conveyor is not None and c.get_entity_type(conveyor) in [EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR]:
                conv_dir = c.get_direction(conveyor)
                if conv_dir != split_dir and conv_dir == p.direction_to(split_pos):
                    adj.append(p)

        if len(adj) == 0:
            return

        self.replace = adj