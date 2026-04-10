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

# BUILDER BOTS
from botRolex.builder import Harvester
from botRolex.builderTorretas import Torreta
from botRolex.builderAtaque2 import Ataque
from botRolex.defensivo import Defensivo
from botRolex.builderMuros import Muros
from botRolex.healer import Healer
from botRolex.revientatotos import Revientatotos

# TORRETAS
from torretaRolex.sentinel import run_sentinel
from torretaRolex.breach import run_breach
from torretaRolex.gunner import run_gunner
from torretaRolex.launcher import Launcher

class Player:
    def __init__(self):
        # BRAIN
        self.brain = None

        # Core Vars
        self.num_spawned = 0 # number of builder bots spawned so far (core)
        self.num_tbuilders = 0 # numero de builders torreta


    def run(self, ct: Controller) -> None:
        width = ct.get_map_width()

        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            run_core(self, ct)
        elif etype == EntityType.BUILDER_BOT:
            if(self.brain is None): # primera ronda de su vida
                #si hay bot enemigo cerca, pasar a healer
                entities = ct.get_nearby_entities()
                for e in entities:
                    if ct.get_entity_type(e) == EntityType.BUILDER_BOT and ct.get_team(e) != ct.get_team():
                        self.brain = Revientatotos(ct)
                        break

                round = ct.get_current_round()
                # MODO PRUEBA MASIVA REVIENTATOTOS: 80% de bots
                if self.brain is None and round >= 10 and ct.get_id() % 10 < 8:
                    self.brain = Revientatotos(ct)  # deambulan por todo el mapa
                elif self.brain is None and round > 50:
                    if ct.get_id() % 10 == 8:
                        self.brain = Healer(ct) # healer
                    else:
                        self.brain = Harvester(ct) # un poco de economía para torretas
                elif self.brain is None and round == 1:
                    self.brain = Defensivo(ct) # defensivo
                elif self.brain is None and round == 2:
                    if width < 20:
                        self.brain = Ataque(ct) # ataque
                    else:
                        self.brain = Revientatotos(ct) # normal
                elif self.brain is None and round == 4:
                    self.brain = Ataque(ct) # ataque
                elif self.brain is None and round == 3:
                    self.brain = Harvester(ct) # torreta
                elif self.brain is None:
                    self.brain = Harvester(ct) # normal

            self.brain.run(ct)

        elif etype == EntityType.SENTINEL:
            run_sentinel(self, ct)
        elif etype == EntityType.BREACH:
            run_breach(self, ct)
        elif etype == EntityType.GUNNER:
            run_gunner(self, ct)
        elif etype == EntityType.LAUNCHER:
            if self.brain is None:
                self.brain = Launcher(ct)
            
            self.brain.run(ct)

            