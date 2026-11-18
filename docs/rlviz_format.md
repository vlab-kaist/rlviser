# rlviz stream format (v1)

A **stream** is a sequence of MessagePack values: one header map, then any number of frame maps.

* A **replay file** (`.rlviz`) is a stream compressed with zstd (one zstd frame or several).
* A **live stream** is the same stream, uncompressed, over a TCP connection to the viewer
  (127.0.0.1:45300 by default). Each new connection starts a new timeline.

Readers ignore keys they do not know, so producers can add optional fields without a version bump.
A change that old readers would misread bumps `version`. Producer: `python/rlviz` (`format.py`,
`sim.py`). Reader: the viewer (`src/rlviz/format.rs`) and `rlviz.format.read_replay`.

## Conventions

* Rocket League world coordinates in uu, z up (as RocketSim). Velocities in uu/s, angular velocity in
  rad/s.
* Rotations are given as a 3x3 matrix flattened by rows: forward, right, up (`rot`, 9 floats).
* Floats may be 32-bit (the Python writer uses single floats).
* `tick` is the simulator tick count. Frames must be in increasing tick order; the stride between
  frames is free (every tick, every 8 ticks, irregular).
* Colors are RGBA in 0..1.

## Header

| key | type | |
|---|---|---|
| `format` | string | `"rlviz"` |
| `version` | int | `1` |
| `game_mode` | string | `soccar`, `hoops`, `heatseeker`, `snowday`, `dropshot`, `void` |
| `tick_rate` | float | ticks per second (120) |
| `pads` | list | `{pos: [x,y,z], big: bool}`, the boost pads in a fixed order |
| `cars` | list | `{id, team (0 blue, 1 orange), name, config}` |
| `meta` | map | free: `source`, `created`, checkpoints, seeds, notes, ... |

`config` is the car's hitbox and wheels (as RocketSim's `CarConfig`):
`{hitbox_size: [3], hitbox_offset: [3], front_wheels: {radius, suspension_rest, offset: [3]},
back_wheels: {...}, dodge_deadzone}`. The viewer picks the car body from `hitbox_size`. Without
`config` the car is drawn as an Octane; a car missing from the header is drawn as an Octane on the blue
team.

## Frame

| key | type | |
|---|---|---|
| `tick` | int | |
| `ball` | body | `{pos, vel, ang_vel, rot}` |
| `cars` | list | body keys plus the car keys below |
| `pads` | list of bool | active flag per header pad |
| `draw` | list | optional debug draw groups |

Car keys (all optional except `id`): `id`, `boost` (0–100), `on_ground`, `wheels` (4 bools: front
left, front right, rear left, rear right), `jumped`, `double_jumped`, `flipped`, `demoed`,
`supersonic`, `boosting`, `controls` (8 floats: throttle, steer, pitch, yaw, roll, jump, boost,
handbrake).

## Draw groups

`draw` is a list of `{name: string, prims: [primitive, ...]}`.

A group stays in effect on later frames until a frame carries a group with the same name again;
`prims: []` clears it. So a producer can send a group only when it changes (or every N frames), and
the viewer shows, at any frame, the latest version of each group at or before that frame.

Primitives (`t` selects the type):

| `t` | keys | |
|---|---|---|
| `line` | `a`, `b`, `color` | |
| `polyline` | `pts` (list of points), `color` | |
| `arrow` | `a`, `b`, `color` | head length from the arrow length |
| `sphere` | `c`, `r`, `color`, `fill` (optional bool) | wireframe; `fill`: shaded solid |
| `box` | `c`, `size` ([3] full extents along forward, right, up), `color`, `rot` (optional [9], rows forward, right, up as a body's `rot`; default axis-aligned), `fill` (optional) | wireframe; `fill`: shaded solid |
| `mesh` | `v` (points), `tri` (list of [i, j, k] into `v`), `color`, `colors` (optional, one per point, replaces `color`), `wire` (optional, also draw the edges) | shaded triangles seen from both sides: a surface, or the boundary of a volume |
| `text` | `pos`, `text`, `color` | label centered above a world point; `\n` for lines |
| `text2d` | `pos` ([x, y] fractions of the window from the top left), `text`, `color` | |

Alpha below 1 makes `mesh` and filled `box`/`sphere` translucent. Filled primitives are drawn as
scene meshes, built once per group version, so a large `mesh` (thousands of triangles) is fine
when the group changes only now and then; resending it every frame rebuilds it every frame.

Viewers skip primitive types they don't know, so new types can be added without a version change.
(`box`, `mesh` and `fill` were added after the first version of v1; older viewers reject them.)
