from cambc import Controller, Direction, EntityType, Environment, Position
import math
import random

class BugNav:
    followingWall = False
    hitPoint = None

    wallDir = None
    visitedStates = set()
    start = None
    prevGoal = None

    def reset(self):
        self.followingWall = False
        self.hitPoint = None
        self.wallDir = None
        self.visitedStates.clear()

    # CHANGED: helper para convertir una dirección objetivo (posible diagonal)
    # a una dirección cardinal cuando four_dirs=True.
    def _cardinal_direction_towards(self, current: Position, goal: Position) -> Direction:
        dx = goal.x - current.x
        dy = goal.y - current.y
        # si estamos exactamente en la meta, devolver CENTRE
        if dx == 0 and dy == 0:
            return Direction.CENTRE
        # preferir el eje con mayor distancia absoluta
        if abs(dx) > abs(dy):
            return Direction.EAST if dx > 0 else Direction.WEST
        else:
            return Direction.SOUTH if dy > 0 else Direction.NORTH

    # listas ordenadas: (CW order) usaremos índices para rotaciones coherentes
    fdirs = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]  # CHANGED: orden consistente (clockwise)
    dirs = [Direction.NORTH, Direction.NORTHEAST, Direction.EAST, Direction.SOUTHEAST,
            Direction.SOUTH, Direction.SOUTHWEST, Direction.WEST, Direction.NORTHWEST]  # CHANGED: orden clockwise de 8-dir

    def moveTo(self, c: Controller, goal: Position, four_dirs: bool):
        current = c.get_position()

        if(goal != self.prevGoal):
            self.reset()
            self.start = current
            self.prevGoal = goal

        # si no se está siguiendo pared, intentar avanzar en línea recta hacia la meta
        if(not self.followingWall):
            if four_dirs:
                nextDir = self._cardinal_direction_towards(current, goal)  # CHANGED: no usar rotate_left para "quitar diagonal"
            else:
                nextDir = current.direction_to(goal)

            # si la dirección es CENTRE (ya en goal), devolver CENTRE
            if nextDir == Direction.CENTRE:
                return Direction.CENTRE

            # intentar moverse o preparar casilla (road)
            if(c.can_move(nextDir) or c.can_build_road(current.add(nextDir))):
                return nextDir

            # En modo four_dirs: intentar la dirección opuesta del diagonal "fallback" ya no aplica aquí.
            # Si no se puede, comenzamos a seguir la pared.
            self.followingWall = True
            self.hitPoint = current
            # guardar la dirección del obstáculo (la que intentamos movernos)
            self.wallDir = nextDir
            self.visitedStates.clear()

        # estamos siguiendo la pared
        c.draw_indicator_dot(current, 245, 63, 39)

        # CHANGED: detección de bucle por estado (posición + orientación de pared)
        stateKey = (current.x, current.y, str(self.wallDir))
        if stateKey in self.visitedStates:
            # si volvemos a un estado previamente visto: damos por perdido
            return Direction.CENTRE
        self.visitedStates.add(stateKey)

        # NO recalcular self.wallDir = current.direction_to(goal) !  <-- QUITADO (era bug)
        nextDir = self.followWall(c, four_dirs=four_dirs)

        if(nextDir == Direction.CENTRE):
            # Process Giving UP
            return Direction.CENTRE

        # Leave obstacle if back on M-line closer to goal
        nextPos = current.add(nextDir)
        # mantener mismo criterio que tenías (comparación de distancias al goal)
        if((self.onMline(nextPos, c) and nextPos.distance_squared(goal) < self.hitPoint.distance_squared(goal))):
            self.followingWall = False
            self.visitedStates.clear()

        return nextDir

    def followWall(self, c: Controller, four_dirs: bool):
        """
        CHANGED:
        - Usar listas predefinidas (fdirs o dirs) para rotar de forma consistente.
        - Emular rotate_left() iterando la lista desde wallDir hacia la izquierda (CCW).
        - Para four_dirs iteramos sobre fdirs, para 8 dirs sobre dirs.
        - Orden: comprobamos primero la dirección "a la izquierda" relativa a wallDir,
          luego 'recto', luego 'derecha', etc. (regla de mano izquierda).
        """
        current = c.get_position()

        dirs_list = self.fdirs if four_dirs else self.dirs

        # si wallDir no está en la lista (caso inicial o valor inesperado), buscar la dirección más cercana
        try:
            idx = dirs_list.index(self.wallDir)
        except ValueError:
            # CHANGED: intentar mapear wallDir aproximada a un índice; si falla, arrancar desde 0
            # (esto evita excepciones si wallDir es diagonal en modo four_dirs, etc.)
            # buscamos la dirección de la lista que tenga menor delta angular aproximado
            best_idx = 0
            best_dist = None
            for i, d in enumerate(dirs_list):
                ddx, ddy = d.delta()
                wdx, wdy = self.wallDir.delta() if self.wallDir is not None else (0,0)
                dist = (ddx - wdx)**2 + (ddy - wdy)**2
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_idx = i
            idx = best_idx

        # aplicar regla de mano izquierda: comprobar en orden CCW desde wallDir
        n = len(dirs_list)
        for i in range(n):
            # dir candidate = dirs_list[(idx - i) % n]  # (idx - 1) is left of idx if list is clockwise
            dir_candidate = dirs_list[(idx - i) % n]  # CHANGED: CCW ordering (left first)
            # Si estamos en modo four_dirs y la dirección candidata no es cardinal (en teoría no pasa
            # porque fdirs solo contiene cardinales), la descartamos; pero lo dejamos por seguridad.
            dx, dy = dir_candidate.delta()
            if four_dirs and dx != 0 and dy != 0:
                continue

            if(c.can_move(dir_candidate) or c.can_build_road(current.add(dir_candidate))):
                # actualizar wallDir hacia la dirección con la que avanzaremos
                self.wallDir = dir_candidate
                return dir_candidate

        # si no encontramos ninguna dirección válida, devolvemos CENTRE (giving up)
        return Direction.CENTRE

    def onMline(self, p: Position, c: Controller):
        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prevGoal))
        d3 = math.sqrt(self.start.distance_squared(self.prevGoal))

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)

        return abs((d1 + d2) - d3) < 0.5

    dvd = None
    # (las listas fdirs, dirs ya definidas arriba se usan también aquí)
    def moveDvD(self, c: Controller, four_dirs: bool):
        current = c.get_position()
        if(self.dvd is None):
            self.dvd = random.choice(self.fdirs) if four_dirs else random.choice(self.dirs)

        if(c.can_move(self.dvd) or c.can_build_road(current.add(self.dvd))):
            return self.dvd

        self.dvd = random.choice(self.fdirs) if four_dirs else random.choice(self.dirs)
        return self.dvd