> ## Documentation Index
> Fetch the complete documentation index at: https://docs.battlecode.cam/llms.txt
> Use this file to discover all available pages before exploring further.

# Turrets

> Defensive and offensive combat units — gunner, sentinel, breach, and launcher.

Every turret **except the launcher** faces in one of **8 directions**. Ammo must be fed to turrets via conveyors, from any direction except the direction the turret is facing. Diagonal turrets can be fed from all four sides.

Ammo-based turrets can hold up to one stack of one resource type and only accept incoming resources when completely empty.

You can inspect raw turret geometry with `c.get_attackable_tiles()` on a real
turret or `c.get_attackable_tiles_from(position, direction, turret_type)` from
any controller. These queries ignore ammo, cooldown, occupancy, blockers, and
other legality checks. Use `c.can_fire()` to check a real turret's current shot
legality, or `c.can_fire_from(...)` to test a hypothetical shot against the
current map's range and obstruction rules.

<Info>
  If a builder bot is standing on a building, turret attacks on that tile hit
  **only the builder bot**.
</Info>

<Info>
  Raw axionite fed into a turret is **destroyed**. Only the ammo types listed
  below have any effect.
</Info>

## Gunner

Has a vision radius of √13. Fires along the forward ray up to range. Empty
tiles and markers do **not** block line of sight. Markers are still targetable.
Walls block the ray but are not targetable. Builder bots and non-marker
buildings are both targetable and blocking, so nothing beyond the first such
blocker is legal. Using refined axionite as ammo deals **30 damage** instead of 10.

<Info>
  Markers are the only occupied tiles that do **not** block a gunner. Walls
  block but are not targetable. Builder bots and non-marker buildings are both
  targetable and blocking.
</Info>

<Tip>
  `c.get_gunner_target()` returns the closest **targetable** occupied tile on
  the forward line. It may return a marker even if a farther legal target also
  exists behind that marker.
</Tip>

<Info>
  Gunners can rotate to any direction with `c.rotate(direction)`. This costs
  **10 Ti** from the global pool and applies a **1-turn cooldown**. Use
  `c.can_rotate(direction)` to preflight the move.
</Info>

| Property      | Value                         |
| ------------- | ----------------------------- |
| HP            | 40                            |
| Base cost     | 10 Ti                         |
| Scaling       | 10%                           |
| Damage        | 10 (30 with refined axionite) |
| Reload        | 1 round                       |
| Ammo per shot | 2                             |
| Vision r²     | 13                            |
| Attack r²     | 13 (same as vision)           |

<Tabs>
  <Tab title="Cardinal">
  </Tab>

  <Tab title="Diagonal">
  </Tab>
</Tabs>

## Sentinel

High range support turret. Can hit all tiles within **1 king move** (Chebyshev distance) of the straight line in its facing direction, within vision range.

Using refined axionite instead of titanium as ammo adds **+5 to the action and move cooldown** of any unit directly hit — acting as a stun.

| Property      | Value               |
| ------------- | ------------------- |
| HP            | 30                  |
| Base cost     | 30 Ti               |
| Scaling       | 20%                 |
| Damage        | 18                  |
| Reload        | 3 rounds            |
| Ammo per shot | 10                  |
| Vision r²     | 32                  |
| Attack r²     | 32 (same as vision) |

<Tabs>
  <Tab title="Cardinal">
  </Tab>

  <Tab title="Diagonal">
  </Tab>
</Tabs>

<Tip>
  Sentinels with refined axionite ammo still disrupt builder bots by delaying
  both movement and actions.
</Tip>

## Breach

Very high damage with **splash**. Attacks in a **180° cone** in the facing direction.

| Property      | Value                                       |
| ------------- | ------------------------------------------- |
| HP            | 60                                          |
| Base cost     | 15 Ti, 10 Ax                                |
| Scaling       | 10%                                         |
| Damage        | 40 direct + 20 splash (8 surrounding tiles) |
| Reload        | 1 round                                     |
| Ammo per shot | 5 (refined axionite only)                   |
| Vision r²     | 13                                          |
| Attack r²     | 5                                           |

<Tabs>
  <Tab title="Cardinal">
  </Tab>

  <Tab title="Diagonal">
  </Tab>
</Tabs>

<Warning>
  Breach turrets have **friendly fire** on the splash damage (8 surrounding
  tiles). They do not damage themselves.
</Warning>

## Launcher

Picks up and **throws adjacent builder bots** to a target tile within range. The target tile must be bot-passable. Unlike other turrets, launchers have **no facing direction** and do not use ammo.

| Property  | Value               |
| --------- | ------------------- |
| HP        | 30                  |
| Base cost | 20 Ti               |
| Scaling   | 10%                 |
| Reload    | 1 round             |
| Vision r² | 26                  |
| Attack r² | 26 (same as vision) |

```python  theme={"dark"}
# Build a launcher (no direction needed)
c.build_launcher(pos)

# Launch a builder bot to a distant position
if c.can_launch(bot_pos, target_pos):
    c.launch(bot_pos, target_pos)
```


Built with [Mintlify](https://mintlify.com).