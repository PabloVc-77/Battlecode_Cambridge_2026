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

    _MAX_HAND_SWITCHES = 2
    _hand_switches = 0
    _use_left_hand = True 

    def _switch_hand(self):
        """Cambia de mano (left↔right) y resetea los visited states."""
        self._use_left_hand = not self._use_left_hand
        self._hand_switches += 1
        self.visitedStates.clear()
        self._wall_steps = 0

    def reset(self):
        self.followingWall = False
        self.hitPoint = None
        self.wallDir = None
        self.visitedStates.clear()

    def moveTo(self, c: Controller, goal: Position, four_dirs: bool):
        current = c.get_position()

        if(goal != self.prevGoal):
            self.reset()
            self.start = current
            self.prevGoal = goal


        if(not self.followingWall):
            nextDir = current.direction_to(goal)
            flag = False
            if(four_dirs):
                (dx, dy) = nextDir.delta()
                if(dx != 0 and dy != 0):
                    flag = True
                    nextDir = nextDir.rotate_left()
                    

            if(c.can_move(nextDir) or c.can_build_road(current.add(nextDir))):
                return nextDir
            elif(four_dirs and flag):
                nextDir = nextDir.rotate_right().rotate_right()
                if(c.can_move(nextDir) or c.can_build_road(current.add(nextDir))):
                    return nextDir
            
            # Hit obstacle → start wall following
            self.followingWall = True
            self.hitPoint = current
            self.wallDir = nextDir

            self.visitedStates.clear()
        
        c.draw_indicator_dot(current, 245, 63, 39)
        self.wallDir = current.direction_to(goal)
        nextDir = self.followWall(c, four_dirs=four_dirs)

        # Detección de bucle por estado (posición + dirección del muro)
        stateKey = (current.x, current.y, str(self.wallDir))
        if stateKey in self.visitedStates:
            # Bucle detectado → intentar cambiar de mano
            if self._hand_switches < self._MAX_HAND_SWITCHES:
                self._switch_hand()
                self.hitPoint = current
                c.draw_indicator_dot(current, 63, 63, 245)  # azul = cambio de mano
            else:
                # Ambas manos fallaron → greedy step
                greedy = self._greedy_step(c, current, goal, four_dirs)
                if greedy != Direction.CENTRE:
                    self.reset()
                    self._hand_switches = 0
                    c.draw_indicator_dot(current, 245, 245, 39)  # amarillo = greedy
                    return greedy
                # Completamente stuck
                self.reset()
                self._hand_switches = 0
                return Direction.CENTRE

        self.visitedStates.add(stateKey)
        

        
        # Leave obstacle if back on M-line closer to goal
        # !!! Add seansing condition: If I see goal and no obstacle leave followingWall !!!
        nextPos = current.add(nextDir)
        if((self.onMline(nextPos, c) and nextPos.distance_squared(goal) < self.hitPoint.distance_squared(goal))):
            self.followingWall = False
            self.visitedStates.clear()

        return nextDir
    
    prevWallDir = Direction.CENTRE
    def followWall(self, c: Controller, four_dirs: bool):
        dir = self.wallDir
        current = c.get_position()
        for i in range(8):
            dir = dir.rotate_left()

            dx, dy = dir.delta()
            if(four_dirs and dx != 0 and dy != 0):
                continue
            
            if(dir.opposite() == self.prevWallDir):
                continue

            if(c.can_move(dir) or c.can_build_road(current.add(dir))):
                pared = current.add(self.wallDir).add(dir)
                if c.is_tile_empty(pared) or c.is_tile_passable(pared):
                    # La pared no esta donde se esperaba
                    self.wallDir = current.add(dir).direction_to(current.add(self.prevWallDir))
                
                self.prevWallDir = self.wallDir
                return dir

        return Direction.CENTRE
    
    def onMline(self, p: Position, c: Controller):
        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prevGoal))
        d3 = math.sqrt(self.start.distance_squared(self.prevGoal))

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)

        return abs((d1 + d2) - d3) < 0.5
    
    def _greedy_step(self, c: Controller, current: Position, goal: Position, four_dirs: bool):
        """Intenta moverse en la dirección que minimice distancia al goal."""
        dirs_list = self.fdirs if four_dirs else self.dirs
        best_dir = Direction.CENTRE
        best_dist = current.distance_squared(goal)

        for d in dirs_list:
            if c.can_move(d) or c.can_build_road(current.add(d)):
                npos = current.add(d)
                nd = npos.distance_squared(goal)
                if nd < best_dist:
                    best_dist = nd
                    best_dir = d

        # Si greedy no mejora, al menos mover a cualquier lado pasable
        if best_dir == Direction.CENTRE:
            for d in dirs_list:
                if c.can_move(d) or c.can_build_road(current.add(d)):
                    return d

        return best_dir
    
    dvd = None
    fdirs = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
    dirs = [Direction.NORTH, Direction.NORTHEAST, Direction.NORTHWEST, Direction.WEST, Direction.EAST, Direction.SOUTHEAST, Direction.SOUTH, Direction.SOUTHWEST]
    def moveDvD(self, c: Controller, four_dirs: bool):
        current = c.get_position()
        if(self.dvd is None):
            self.dvd = random.choice(self.fdirs) if four_dirs else random.choice(self.dirs)
        
        if(c.can_move(self.dvd) or c.can_build_road(current.add(self.dvd))):
            return self.dvd
        
        self.dvd = random.choice(self.fdirs) if four_dirs else random.choice(self.dirs)
        return self.dvd


