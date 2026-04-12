# Specification: Merge trucha_v2_2_catapulta and trucha_v2_4 into trucha_v2_6

## Goal
The objective of this track is to create a new bot version, `trucha_v2_6`, by merging the robust core and macro-management of `trucha_v2_4` with the advanced pathfinding logic currently implemented in `trucha_v2_2_catapulta`. Additionally, the integrated pathfinding system will be optimized for better performance and map coverage.

## Scope
- Create a new bot directory: `bots/trucha_v2_6`.
- Use `bots/trucha_v2_4` as the baseline for macro-management, unit production, and defensive structures.
- Extract the pathfinding logic (e.g., `bugnav`, `bignav_a_mem`) from `bots/trucha_v2_2_catapulta`.
- Integrate the extracted pathfinding logic into the `trucha_v2_6` main loop and unit controllers.
- Identify and implement optimizations in the navigation system to improve efficiency and resource discovery.

## Functional Requirements
- **Integration:** `trucha_v2_6` must successfully combine the features of both parent bots without regressions in existing behaviors.
- **Pathfinding:** The bot must use the `catapulta` variant's navigation for movement, especially for long-distance travel and obstacle avoidance.
- **Optimization:** Improved navigation should result in faster map scouting and resource acquisition compared to `v2_4`.

## Non-Functional Requirements
- **Performance:** Pathfinding must remain within the turn-time limits of the Battlecode engine.
- **Maintainability:** The merged codebase should follow the "Self-Documenting Code" guideline.
- **Testing:** New integration points must be covered by tests following the project's TDD workflow.