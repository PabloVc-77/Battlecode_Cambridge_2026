# Product Guide: Battlecode Cambridge 2026 Bot

## Initial Concept
Develop an AI bot for the Cambridge Battlecode 2026 competition using Python, focusing on defensive and resource-oriented strategies.

## Core Strategy
The primary overarching strategy is a **Defensive Turtle** approach. The bot will prioritize building strong defenses and securing a robust infrastructure to withstand early aggression, setting the stage for a massive late-game push.

## Priority Systems
Development will focus on two main subsystems:
1. **Pathfinding & Navigation:** Improving and integrating custom pathfinding algorithms like `bugnav` and memory-based `bignav_a_mem` to ensure efficient map traversal.
2. **Macro Management:** Optimizing global resource allocation, building placement, and overall economy to out-scale opponents.

## Win Condition
Our primary intended win condition is **Resource Domination**. We aim to starve the opponent by securing and controlling the majority of the map's resources over time.

## Bot Variants Management
Currently, the most functional and relevant bot is `trucha_v2_4`. Ongoing work is focused on improving the pathfinding systems specifically within the `trucha_v2_2_catapulta` variant. Other variants are less relevant, and our efforts will be concentrated on these two main branches.