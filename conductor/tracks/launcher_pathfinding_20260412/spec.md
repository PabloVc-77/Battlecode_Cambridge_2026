# Specification: Launcher-Assisted Pathfinding

## Overview
Enhance the pathfinding capabilities of the `trucha_v2_6` bot by integrating reusable launchers. Builder bots will construct launchers to traverse otherwise impassable terrain (walls), and all bots will reuse existing launchers to optimize their routes.

## Functional Requirements
- **Launcher Construction:** Builder bots must dynamically build launchers strictly when their path is completely blocked by an obstacle and no walking path is found by A*.
- **Resource Management:** Construction of new launchers is contingent upon the global resource pool exceeding a predefined safe reserve threshold.
- **Launcher Reuse:** Bots must utilize existing launchers to shorten their travel distance.
- **Persistent Mapping:** The locations of discovered launchers must be recorded in the bot's persistent memory map to facilitate pathfinding decisions without requiring continuous line-of-sight.
- **Range Constraints:** The pathfinding logic must accurately account for the specific range of the launcher, which operates as a circle extending one tile beyond standard robot vision.

## Non-Functional Requirements
- **Performance:** Integrating launcher logic into the pathfinding must remain within the 2ms per round CPU limit.
- **Scalability:** The persistent mapping of launchers must efficiently handle updates to the map state.

## Acceptance Criteria
- A builder bot encountering a blocking wall will build a launcher (resources permitting) and use it to cross the obstacle.
- Bots encountering a previously built launcher will factor it into their path calculation and use it if it provides a faster route.
- A bot will not build a launcher if the global resources fall below the designated threshold.
- Launcher locations are retained in memory and influence pathing decisions outside the bot's immediate vision.