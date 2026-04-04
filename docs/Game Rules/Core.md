> ## Documentation Index
> Fetch the complete documentation index at: https://docs.battlecode.cam/llms.txt
> Use this file to discover all available pages before exploring further.

# Core

> Your central building — if it's destroyed, you lose.


The core is each team's central building. **If your core is destroyed, you lose the game.** Each team starts with one core.

## Properties

| Property       | Value           |
| -------------- | --------------- |
| HP             | 500             |
| Footprint      | 3×3             |
| Vision radius² | 36              |
| Action radius² | 8 (from centre) |

## Spawning

The core can **spawn one builder bot per round** on any of the 9 tiles it occupies. Spawning costs one action cooldown.

<Info>
  Each team can have at most **50 living units total**, including the core. That means you can have at most **49 additional living units**. Use `c.get_unit_count()` together with `GameConstants.MAX_TEAM_UNITS` if you want the exact numbers. `c.can_spawn()` and any unit-producing `c.can_build_*()` method already account for the cap.
</Info>

```python  theme={"dark"}
# Spawn a builder on an empty core tile
pos = c.get_position()  # centre of the 3x3 core
for dx in range(-1, 2):
    for dy in range(-1, 2):
        target = Position(pos.x + dx, pos.y + dy)
        if c.can_spawn(target):
            c.spawn_builder(target)
            break
```


## Resource delivery

Resources must be transferred to the core via [conveyors](/spec/conveyors) to be added to your team's global resource pool, which is used for building.

Raw axionite delivered to the core is **destroyed**, so refine it first if you want to keep it.

## Conversion

The core can convert refined axionite from the global resource pool into
titanium with `c.convert(amount)`.

$$
1 \text{ Ax} \rightarrow 4 \text{ Ti}
$$

Converted axionite is removed from the Ax collected stat and added to the Ti
collected stat.


Built with [Mintlify](https://mintlify.com).