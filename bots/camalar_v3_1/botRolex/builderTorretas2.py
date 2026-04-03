from operator import pos

from cambc import Controller, Direction, EntityType, Environment, Position
import math
import bignav_a_mem as bugnav

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()

    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0

class Torreta:
    def __init__(self, ct: Controller):
        self.objetivos = []
        self.spawn = None

        # Builder_Torretas Vars
        self.enemy_core_pos = None
        self.my_core = None
        self.simetry = 0
        self.enemy_core = []
        self.turrets_built = 0
        self.breach_built = 0
        self.caminos_objetivo = []
        self.breach_objetivo_pendiente = None

        self.navegador = bugnav.BugNav()

        builds = ct.get_nearby_buildings()
        for b in builds:
            if ct.get_entity_type(b) == EntityType.CORE:
                self.spawn = ct.get_position(b)
                break
        pass

    def run(self, c: Controller):
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

        if c.can_heal(c.get_position()):
            c.heal(c.get_position())

        if self.enemy_core_pos is None:
            self.find_enemy_core(c)
        else:
            #if not find_connected_to_core(self, c): construir breach pegado al core, por hacer
            self.find_harvesters(c)


    def find_enemy_core(self, c: Controller):
        enemyC = self.enemy_core[self.simetry % 3]

        # Debug: línea amarilla hacia el objetivo estimado del core enemigo
        c.draw_indicator_line(c.get_position(), enemyC, 255, 140, 0)

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
            direccion_nexo = prev_pos.direction_to(self.enemy_core_pos)
            if c.can_build_sentinel(prev_pos, direccion_nexo):
                c.build_sentinel(prev_pos, direccion_nexo)
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