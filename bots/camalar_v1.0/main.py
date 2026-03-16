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
import bugnav 

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

class Player:
    def __init__(self):
        self.num_spawned = 0 # number of builder bots spawned so far (core)
        self.navegador = bugnav.BugNav()

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            run_core(self, ct)
        elif etype == EntityType.BUILDER_BOT:
            run_builder(self, ct)
