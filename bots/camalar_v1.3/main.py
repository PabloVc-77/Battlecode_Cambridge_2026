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
from botRolex.builderTorretas import run_builder_torretas
from botRolex.defensivo import run_defensivo
import bignav_opus as bugnav

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
# types of builder bots
BUILDERS = ["normal", "torreta", "defensivo"]

class Player:
    def __init__(self):
        # Core Vars
        self.num_spawned = 0 # number of builder bots spawned so far (core)
        self.num_tbuilders = 0 # numero de builders torreta

        # Builder Vars
        self.navegador = bugnav.BugNav()
        self.spawn = None
        self.conveyor_mode = False
        self.objetivos = []
        self.current_target = None
        
        # Type of Builder
        self.builder_type = None

        # Builder_Torretas Vars
        self.enemy_core_pos = None
        self.my_core = None
        self.simetry = 0
        self.enemy_core = []
        self.enemy_core_adjacent = []
        
        self.analysis_tile = 0        
        self.analysis_mode = -1

        # Builder_Defensivo Vars
        # self.my_core
        self.furnace = False
        self.splitter_pos = None
        self.furnace_pos = None
        self.fase2 = False
        self.fase2 = 0
        self.replace = []


    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            run_core(self, ct)
        elif etype == EntityType.BUILDER_BOT:
            if(self.spawn is None): # primera ronda de su vida
                self.spawn = ct.get_position()
                if ct.get_current_round() >= 1 and ct.get_current_round() <= 3: # No entra aqui
                    self.builder_type = BUILDERS[1] # torreta
                elif ct.get_current_round() == -1:
                    self.builder_type = BUILDERS[2] # defensivo
                else:
                    self.builder_type = BUILDERS[0] # normal

            if self.builder_type == BUILDERS[0]:
                run_builder(self, ct)
            elif self.builder_type == BUILDERS[1]:
                run_builder_torretas(self, ct)
            elif self.builder_type == BUILDERS[2]:
                run_defensivo(self, ct)
