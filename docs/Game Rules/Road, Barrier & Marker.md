> ## Documentation Index
> Fetch the complete documentation index at: https://docs.battlecode.cam/llms.txt
> Use this file to discover all available pages before exploring further.

# Road, Barrier & Marker

> Utility buildings — walkable paths, defensive walls, and inter-unit communication.

## Road

Walkable tiles for builder bots to move on. The cheapest building.

| Property  | Value |
| --------- | ----- |
| HP        | 5     |
| Base cost | 1 Ti  |
| Scaling   | 0.5%  |

## Barrier

Cheap, takes up space, and has high HP. Useful for blocking enemy paths or protecting key buildings.

| Property  | Value |
| --------- | ----- |
| HP        | 30    |
| Base cost | 3 Ti  |
| Scaling   | 1%    |

## Marker

A tile containing a single **unsigned 32-bit integer** that can be read by any allied unit. Building a marker is completely free and does **not** cost action cooldown — you may place at most one marker per round.

Any team may build over markers, destroying them.

Markers remain targetable by gunners, but unlike walls, builder bots, and
non-marker buildings they do **not** block line of sight or shield occupied
tiles behind them.

| Property | Value |
| -------- | ----- |
| HP       | 1     |
| Cost     | Free  |

<Info>
  Markers are the **only form of communication** between allied units. Global variables are not shared between `Player` instances — each unit has its own isolated Python environment.
</Info>

<Tip>
  All units (core, builder bots, and turrets) can place markers — not just builder bots.
</Tip>

```python  theme={"dark"}
# Write a value to a marker
if c.can_place_marker(pos):
    c.place_marker(pos, 42)

# Read a marker
building_id = c.get_tile_building_id(pos)
if building_id is not None:
    if c.get_entity_type(building_id) == EntityType.MARKER:
        value = c.get_marker_value(building_id)
```

### Communication patterns

Since each unit's `Player` instance is isolated, markers are essential for coordination:

* **Scouting reports**: Write enemy positions to markers near your core
* **Build orders**: Use marker values as state machine flags
* **Territory claims**: Mark tiles to avoid duplicate work


Built with [Mintlify](https://mintlify.com).