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
        # Detectar Bucle
        #stateKey = (current.x, current.y, self.wallDir)
        #if(stateKey in self.visitedStates):
            # Process Giving UP
         #   return Direction.CENTRE
        #self.visitedStates.add(stateKey)
        
        self.wallDir = current.direction_to(goal)
        nextDir = self.followWall(c, four_dirs=four_dirs)

        if(nextDir == Direction.CENTRE):
            # Process Giving UP
            return Direction.CENTRE
        

        
        # Leave obstacle if back on M-line closer to goal
        # !!! Add seansing condition: If I see goal and no obstacle leave followingWall !!!
        nextPos = current.add(nextDir)
        if((self.onMline(nextPos, c) and nextPos.distance_squared(goal) < self.hitPoint.distance_squared(goal))):
            self.followingWall = False
            self.visitedStates.clear()

        return nextDir
    
    def followWall(self, c: Controller, four_dirs: bool):
        dir = self.wallDir
        current = c.get_position()
        for i in range(8):
            dir = dir.rotate_left()

            dx, dy = dir.delta()
            if(four_dirs and dx != 0 and dy != 0):
                continue

            if(c.can_move(dir) or c.can_build_road(current.add(dir))):
                self.wallDir = dir
                return dir

        return Direction.CENTRE
    
    def onMline(self, p: Position, c: Controller):
        d1 = math.sqrt(self.start.distance_squared(p))
        d2 = math.sqrt(p.distance_squared(self.prevGoal))
        d3 = math.sqrt(self.start.distance_squared(self.prevGoal))

        c.draw_indicator_line(self.start, self.prevGoal, 228, 245, 39)

        return abs((d1 + d2) - d3) < 0.5
    
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


