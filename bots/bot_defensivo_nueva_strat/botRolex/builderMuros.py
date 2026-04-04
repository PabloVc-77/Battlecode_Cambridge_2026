from cambc import Controller, Direction, EntityType, Environment, Position
import bignav_opus as bugnav

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()
    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0


class BuilderMuros:
    def __init__(self, c: Controller):
        self.navegador = bugnav.BugNav()
        self.objetivos = []  # casillas de ore sin cubrir
        self.done = [] #casillas de ore que ya has cubierto, si han puesto harvester es pq es tuyo
        self.my_core = None
    def run(self, c: Controller):

        current = c.get_position()
        self._actualizar_objetivos(c)

        if not self.objetivos:
            # Sin objetivos: explorar
            move_dir = self.navegador.moveExplore(c, four_dirs=False)
            move_pos = current.add(move_dir)
            if c.can_build_road(move_pos):
                c.build_road(move_pos)
            if c.can_move(move_dir):
                c.move(move_dir)
            return

        target = self.objetivos[0]
        c.draw_indicator_line(current, target, 200, 100, 0)

        # Intentar construir barrier en target

        resultado = self._construir_barrier(c, target)
        if resultado:
            if target in self.objetivos:
                self.objetivos.remove(target)
            if target not in self.done:
                self.done.append(target)

    def _actualizar_objetivos(self, c: Controller):
        current = c.get_position()
        lista = c.get_nearby_tiles()
        

        for tile in lista:
            if tile in self.done:
                continue

            env = c.get_tile_env(tile)
            es_ore = (env == Environment.ORE_TITANIUM or
                      (env == Environment.ORE_AXIONITE and c.get_current_round() >= 100))

            if not es_ore:
                if tile in self.objetivos:
                    self.objetivos.remove(tile)
                continue

            building_id = c.get_tile_building_id(tile)
            if building_id is not None:
                entity = c.get_entity_type(building_id)
                # Ignorar si ya hay harvester o barrier propia
                if entity in (EntityType.HARVESTER, EntityType.BARRIER):
                    continue

            if tile not in self.objetivos:
                self.objetivos.append(tile)

        self.objetivos.sort(key=lambda p: current.distance_squared(p))

    def _construir_barrier(self, c: Controller, objetivo: Position) -> bool:
        """
        Igual que construir() del builder original pero solo para BARRIER.
        Devuelve True cuando la casilla está resuelta, False si necesita más turnos.
        """
        current = c.get_position()
        
        # Acercarse si no está en visión
        if not c.is_in_vision(objetivo):
            dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return False


        
        building_id = c.get_tile_building_id(objetivo)

        if building_id is not None:
            entity = c.get_entity_type(building_id)
            team = c.get_team(building_id)

            # Ya hay barrier propia: hecho
            if entity == EntityType.BARRIER and team == c.get_team():
                return True

            # Harvester o muro: skip permanente
            if entity in (EntityType.HARVESTER,):
                return True

            # Road propia: destruir y esperar
            if entity == EntityType.ROAD and team == c.get_team():
                if current.distance_squared(objetivo) > 2:
                    dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
                    next_pos = current.add(dir)
                    if c.can_build_road(next_pos):
                        c.build_road(next_pos)
                    if c.can_move(dir):
                        c.move(dir)
                    return False
                if c.can_destroy(objetivo):
                    c.destroy(objetivo)
                return False

            # Cualquier otra estructura: skip
            return True

        # Casilla vacía: acercarse y construir
        if current.distance_squared(objetivo) > 2:
            dir = self.navegador.moveTo(c, objetivo, four_dirs=False)
            next_pos = current.add(dir)
            if c.can_build_road(next_pos):
                c.build_road(next_pos)
            if c.can_move(dir):
                c.move(dir)
            return False

        if current == objetivo:
            # Salir de encima para poder construir
            for d in [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]:
                adj = objetivo.add(d)
                if _is_in_bounds(c, adj) and c.can_move(d):
                    c.move(d)
                    break
            return False

        if c.can_build_barrier(objetivo):
            c.build_barrier(objetivo)
            return True

        return False