# Implementation Plan: Merge and Optimize trucha_v2_6

## Phase 1: Environment Setup & Analysis [checkpoint: c681011]
- [x] Task: Create `bots/trucha_v2_6` directory and initialize with `v2_4` baseline 2414a0f
- [x] Task: Analyze `trucha_v2_2_catapulta` pathfinding modules for extraction (including launcher.py) 2414a0f
- [x] Task: Conductor - User Manual Verification 'Phase 1: Environment Setup & Analysis' (Protocol in workflow.md) c681011

## Phase 2: Core Integration (TDD) [checkpoint: 26f5854]
- [x] Task: Port pathfinding module to `trucha_v2_6` 9ea0877
    - [x] Write unit tests for pathfinding module integration
    - [x] Implement/port pathfinding logic from `v2_2_catapulta`
- [x] Task: Update unit controllers in `v2_6` to use new pathfinding 09b0a32
    - [x] Write tests for unit movement using the new system
    - [x] Update controller logic to call the new navigation API
- [x] Task: Conductor - User Manual Verification 'Phase 2: Core Integration (TDD)' (Protocol in workflow.md) 26f5854

## Phase 3: Optimization & Refinement
- [ ] Task: Optimize navigation for faster resource discovery
    - [ ] Write benchmarks/tests for resource scouting speed
    - [ ] Implement map-edge or heuristic-based scouting improvements
- [ ] Task: Refine macro-management to complement new navigation
    - [ ] Write tests for build-order efficiency with new movement
    - [ ] Adjust macro triggers based on scouting data
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Optimization & Refinement' (Protocol in workflow.md)

## Phase 4: Final Validation
- [ ] Task: Run full-match simulations against `v2_4` and `v2_2_catapulta`
- [ ] Task: Final code cleanup and documentation update
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Final Validation' (Protocol in workflow.md)