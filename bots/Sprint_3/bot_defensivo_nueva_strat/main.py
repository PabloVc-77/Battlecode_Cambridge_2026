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
from bots.Sprint_3.bot_defensivo_nueva_strat.botRolex.core import run_core 

# BUILDER BOTS
from bots.Sprint_3.bot_defensivo_nueva_strat.botRolex.builder import Harvester
from bots.Sprint_3.bot_defensivo_nueva_strat.botRolex.builderTorretas2 import Torreta
from bots.Sprint_3.bot_defensivo_nueva_strat.botRolex.defensivo import Defensivo

# TORRETAS
from bots.Sprint_3.bot_defensivo_nueva_strat.torretaRolex.sentinel import run_sentinel
from bots.Sprint_3.bot_defensivo_nueva_strat.torretaRolex.breach import run_breach
from bots.Sprint_3.bot_defensivo_nueva_strat.torretaRolex.launcher import Launcher

class Player:
    def __init__(self):
        # BRAIN
        self.brain = None

        # Core Vars
        self.num_spawned = 0 # number of builder bots spawned so far (core)
        self.num_tbuilders = 0 # numero de builders torreta


    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            run_core(self, ct)
        elif etype == EntityType.BUILDER_BOT:
            if(self.brain is None): # primera ronda de su vida
                round = ct.get_current_round()
                if round > 50 and ct.get_id() % 3 != 0:
                   self.brain = Torreta(ct) # torreta
                elif round == 1:
                    self.brain = Defensivo(ct) # defensivo
                else:
                    self.brain = Harvester(ct) # normal

            self.brain.run(ct)

        elif etype == EntityType.SENTINEL:
            run_sentinel(self, ct)
        elif etype == EntityType.BREACH:
            run_breach(self, ct)
        elif etype == EntityType.LAUNCHER:
            if self.brain is None:
                self.brain = Launcher(ct)
            
            self.brain.run(ct)

            
                

