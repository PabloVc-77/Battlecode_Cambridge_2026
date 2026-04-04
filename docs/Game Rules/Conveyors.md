> ## Documentation Index
> Fetch the complete documentation index at: https://docs.battlecode.cam/llms.txt
> Use this file to discover all available pages before exploring further.

# Conveyors

> Transport resources across the map — conveyors, splitters, bridges, and armoured conveyors.

All conveyors can hold **one stack** of any resource, and both accept input and produce output. Basic conveyors, splitters, and armoured conveyors point in one of the **cardinal directions**.

You can inspect the stack currently stored in one of these buildings with `c.get_stored_resource(...)` and `c.get_stored_resource_id(...)`.

## Conveyor

Accepts resources from any of its three non-output directions. Sends its contents in the direction it is pointing if that tile can accept a resource.

| Property  | Value |
| --------- | ----- |
| HP        | 20    |
| Base cost | 3 Ti  |
| Scaling   | 1%    |

```python  theme={"dark"}
# Build a conveyor pointing south
c.build_conveyor(pos, Direction.SOUTH)

# Inspect the stack currently on a conveyor
resource_type = c.get_stored_resource(conveyor_id)
resource_id = c.get_stored_resource_id(conveyor_id)
```

## Splitter

Alternates between outputting in three directions: the primary output and the two adjacent directions. **Only accepts input from the back.** Prioritises directions used least recently.

| Property  | Value |
| --------- | ----- |
| HP        | 20    |
| Base cost | 6 Ti  |
| Scaling   | 1%    |

## Bridge

Outputs its contents to a **specific tile within Euclidean distance 3** (distance² ≤ 9), chosen when built. Bridges bypass directional restrictions — they can feed any building that accepts resources. Accepts input from all directions.

| Property  | Value |
| --------- | ----- |
| HP        | 20    |
| Base cost | 20 Ti |
| Scaling   | 10%   |

```python  theme={"dark"}
# Build a bridge that outputs to a target position
c.build_bridge(bridge_pos, target_pos)
```

## Armoured Conveyor

Same function as a basic conveyor but with **much more HP**. Requires refined axionite to build.

| Property  | Value      |
| --------- | ---------- |
| HP        | 50         |
| Base cost | 5 Ti, 5 Ax |
| Scaling   | 1%         |

## Resource distribution

At the end of each round (after all units have acted), resources are distributed. Buildings that have resources to output attempt to send them to adjacent buildings that can accept them.

Key rules:

* Resources are always moved in **stacks of 10**
* **Resources can be sent to enemy buildings** — be careful with conveyor placement near opponents
* Harvesters and splitters prioritise outputting in directions **used least recently**
* Foundries require one stack each of titanium and raw axionite before outputting one stack of refined axionite
* Turrets only accept resources when completely empty


Built with [Mintlify](https://mintlify.com).