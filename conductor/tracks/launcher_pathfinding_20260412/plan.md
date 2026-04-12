# Implementation Plan: Launcher-Assisted Pathfinding

## Phase 1: Persistent Mapping and Resource Management
- [x] Task: Implement persistent mapping for discovered launchers e590234
    - [x] Write tests for storing and updating launcher positions in the persistent map
    - [x] Implement `BugNav` modifications to track launchers independently
- [ ] Task: Implement resource threshold logic for launcher construction
    - [ ] Write tests ensuring launchers are only built above the safe reserve limit
    - [ ] Add resource check to the jumping mechanic logic
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Persistent Mapping and Resource Management' (Protocol in workflow.md)

## Phase 2: Launcher Construction and Obstacle Traversal
- [ ] Task: Refine launcher construction logic for blocked paths
    - [ ] Write tests for detecting blocked paths and triggering launcher construction
    - [ ] Implement robust construction conditions prioritizing A* failures over simple obstacles
- [ ] Task: Integrate launcher range awareness into landing target selection
    - [ ] Write tests verifying valid landing targets within the extended circular range (robot vision + 1)
    - [ ] Update `_find_unreachable_better_tile` to accurately model this increased range
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Launcher Construction and Obstacle Traversal' (Protocol in workflow.md)

## Phase 3: Launcher Reuse and Optimization
- [ ] Task: Enable discovery and reuse of existing launchers during traversal
    - [ ] Write tests for navigating to and utilizing a recorded, existing launcher
    - [ ] Modify pathfinding logic to actively seek and utilize previously mapped launchers
- [ ] Task: Optimize pathfinding performance with launcher integrations
    - [ ] Write performance benchmarks for the updated pathfinding calculations
    - [ ] Profile and refine the interaction between the persistent map and the jump logic to ensure it stays under the 2ms CPU limit
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Launcher Reuse and Optimization' (Protocol in workflow.md)

## Phase 4: Final Validation
- [ ] Task: Run full-match simulations against the baseline `v2_6` bot to verify improvements
- [ ] Task: Final code cleanup and documentation updates
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Final Validation' (Protocol in workflow.md)