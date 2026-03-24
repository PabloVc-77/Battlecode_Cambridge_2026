"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.

This bot:
  - Core: spawns up to 3 builder bots on random adjacent tiles
  - Builder bot: builds a harvester on any adjacent ore tile, then moves in a
    random direction (laying a road first so the tile is passable), and places
    a marker recording the current round number
"""

import random

from cambc import Controller, Direction, EntityType, Environment, Position
from botRolex.core import run_core 
from botRolex.builder import run_builder
from botRolex.builderTorretas2 import run_builder_torretas2
from botRolex.defensivo import run_defensivo
from torretaRolex.sentinel import run_sentinel
from torretaRolex.breach import run_breach
import bignav_opus as bugnav

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
# types of builder bots
BUILDERS = ["normal", "torreta", "defensivo"]

def _is_in_bounds(c: Controller, pos: Position) -> bool:
    w = c.get_map_width()
    h = c.get_map_height()

    return pos.x < w and pos.y >= 0 and pos.y < h and pos.x >= 0



class Player:
    def __init__(self):
        #General Vars
        self.objetivos = []

        # Core Vars
        self.num_spawned = 0 # number of builder bots spawned so far (core)
        self.num_tbuilders = 0 # numero de builders torreta

        # Builder Vars
        self.navegador = bugnav.BugNav()
        self.spawn = None
        self.conveyor_mode = False
        self.current_target = None

        self.end_bridges = []
        self.mode = 0
            # mode 0: Find Ore
            # mode 1: Place bridge near Ore
            # mode 2: go home
            # mode 3: revisar estructura
        self.last_bridge_end = None
        self.check_pos = None
        
        # Type of Builder
        self.builder_type = None

        # Builder_Torretas Vars
        self.enemy_core_pos = None
        self.my_core = None
        self.simetry = 0
        self.enemy_core = []
        self.turrets_built = 0
        self.breach_built = 0
        self.caminos_objetivo = []
        self.breach_objetivo_pendiente = None

        # Builder_Defensivo Vars
        # self.my_core
        self.furnace = False
        self.splitter_pos = None
        self.furnace_pos = None
        self.fase2 = 0
        self.replace = []

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            run_core(self, ct)
        elif etype == EntityType.BUILDER_BOT:
            if(self.spawn is None): # primera ronda de su vida
                builds = ct.get_nearby_buildings()
                for b in builds:
                    if ct.get_entity_type(b) == EntityType.CORE:
                        self.spawn = ct.get_position(b)
                        break

                round = ct.get_current_round()
                if round >= 180:
                    self.builder_type = BUILDERS[1] # torreta
                elif round == 1:
                    self.builder_type = BUILDERS[2] # defensivo
                else:
                    self.builder_type = BUILDERS[0] # normal
                    
                    s = self.spawn
                    viable_end_of_bridges = [s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST), s.add(Direction.NORTH).add(Direction.NORTH), s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST),
                                             s.add(Direction.EAST).add(Direction.EAST).add(Direction.NORTH), s.add(Direction.EAST).add(Direction.EAST), s.add(Direction.EAST).add(Direction.EAST).add(Direction.SOUTH),
                                             s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST), s.add(Direction.SOUTH).add(Direction.SOUTH), s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST),
                                             s.add(Direction.WEST).add(Direction.WEST).add(Direction.NORTH), s.add(Direction.WEST).add(Direction.WEST), s.add(Direction.WEST).add(Direction.WEST).add(Direction.SOUTH)]
                                             #s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.EAST).add(Direction.EAST), s.add(Direction.NORTH).add(Direction.NORTH).add(Direction.WEST).add(Direction.WEST),
                                             #s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.EAST).add(Direction.EAST), s.add(Direction.SOUTH).add(Direction.SOUTH).add(Direction.WEST).add(Direction.WEST)]
                    for v in viable_end_of_bridges:
                        if _is_in_bounds(ct, v):
                            ct.draw_indicator_dot(v, 245, 73, 39)
                            self.end_bridges.append(v)

            if self.turrets_built >= 3:
                self.objetivos.clear()  # dejar de buscar harvesters
                self.builder_type = BUILDERS[0]  # cambiar a builder normal

            if self.builder_type == BUILDERS[0]:
                run_builder(self, ct)
            elif self.builder_type == BUILDERS[1]:
                run_builder_torretas2(self, ct)
            elif self.builder_type == BUILDERS[2]:
                run_defensivo(self, ct)
        elif etype == EntityType.SENTINEL:
            run_sentinel(self, ct)
        elif etype == EntityType.BREACH:
            run_breach(self, ct)

            
                

