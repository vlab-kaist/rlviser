# rlviz: replays, live games and debug layers

This fork (`vlab-kaist/rlviser`) adds **rlviz** to RLViser:

* the viewer opens **replay files** (`.rlviz`) and plays them on a timeline you can pause, step and
  scrub;
* a simulation can **stream** to the viewer while it runs (same format over TCP); the live game also
  goes onto the timeline, so you can scrub back while it plays;
* frames carry **debug draw groups** (arrows, lines, spheres, labels) that the viewer shows and lets
  you toggle by name;
* a Python package (`python/`, `import rlviz`) runs games on the RocketSim fork, writes replays,
  streams them, and computes the draw groups with small **layer** classes.

The original UDP/FlatBuffers protocol of RLViser (`spec/*.fbs`, ports 34254/45243) is unchanged and
still works next to rlviz.

```
 RocketSim fork ──► rlviz.sim.run ──► Annotator(layers) ──► LiveSink ──TCP──► rlviser timeline ──► scene
 validation npz      (frames)           (adds "draw")       FileSink ──.rlviz─┘     (gizmos, labels)
```

## Quick start

Build the viewer (Linux, X11 only in this fork; needs `rustfmt`):

```sh
cargo build --release --no-default-features
```

Set up Python (3.12, uv) and install the RocketSim fork at a known commit:

```sh
cd python
uv venv --python 3.12 .venv
uv pip install -p .venv -e '.[test]'
uv pip install -p .venv "RocketSim @ git+https://github.com/vlab-kaist/RocketSim@fast-step"
```

The collision meshes are read from `RLVIZ_COLLISION_MESHES`, or `../collision_meshes` next to this
checkout (the `rocket-league-reboot/` layout).

Watch a simulated game live:

```sh
./target/release/rlviser &          # listens for rlviz streams on 127.0.0.1:45300
python/.venv/bin/rlviz demo --live --seconds 60
```

Record one and open it later:

```sh
python/.venv/bin/rlviz demo --out game.rlviz --seconds 60
./target/release/rlviser --replay game.rlviz      # or: rlviser game.rlviz
```

Recompute the layers of a saved replay (states are kept, only the draw groups change):

```sh
python/.venv/bin/rlviz annotate game.rlviz game2.rlviz --layers ball_prediction,car_info
python/.venv/bin/rlviz info game2.rlviz
```

### On the v2 server

The monitor session on v2 belongs to the `vlab` account (display `:1`). To open windows there from
`cwpark`, run once in that session: `xhost +SI:localuser:cwpark`, then `DISPLAY=:1 rlviser ...`.
Without it, run the viewer from the `vlab` account (put files under `/mnt/hdd0/rlbot-shared/`).

Only one viewer can run at a time with the default ports (the original UDP port 45243 and the rlviz
port). A second one needs other ports: `rlviser 34255 45244 --rlviz-port 45301`.

## Viewer controls

A replay starts playing when it opens. `--loop` (or `Loop` in the panel) starts it over after the end,
for leaving a replay running on a screen.

Timeline (bottom panel and keys): `K` play/pause, `,` `.` one frame back/forward, `J` `L` one second
back/forward, `Home` `End`, speed 0.05x–16x, drag the slider to scrub. While a live stream is
connected the timeline follows the newest frame ("LIVE"); scrubbing back stops following, `End`
resumes.

The **Layers** window lists every draw group seen so far; untick one to hide it.

## Recording videos

The viewer records mp4 (H.264, needs `ffmpeg` with libx264). While recording, the timeline advances
by exactly `speed / fps` seconds of game time per rendered frame and every frame is captured, so the
video timing is exact however slowly frames render (on Xvfb too). The timeline panel, the Layers
window and the Menu are hidden in the video; scene, debug draws and labels are kept, from the current
camera.

* **From the viewer**: `Rec` in the timeline panel or `F9` starts at the current frame; `F9` stops
  (or the end of the replay). The file goes next to the replay as `<name>-<unix time>.mp4`.
* **From the command line** (renders and quits, works headless on a virtual display):

  ```sh
  rlviser --replay game.rlviz --record clip.mp4 --from 10 --to 16 --fps 60 --window 1920x1080
  # --record-speed 0.25 for slow motion (game time per video second)
  ```

  `--from`/`--to` are seconds from the start of the replay. Pick the camera beforehand in the Menu or
  in `settings.txt` (`camera_state={"TrackCar":1}`, `"Spectator"`, `{"Director":0}`), or place a fixed
  camera with `--camera X,Y,Z:TX,TY,TZ` (position and look-at point in game coordinates; it switches
  to the free camera, which `settings.txt` then remembers). For example
  `--camera -3000,700,1200:0,3900,500` looks from the side at the orange (+y) goal's half.
  `--follow X,Y,Z` instead keeps the free camera at that offset (game coordinates) from the ball,
  averaged over ±0.75 s around the cursor (stopping at cuts between plays) and kept inside the
  arena; it is a function of the cursor, so recordings and scrubbing are reproducible. For plays
  attacking +y, `--follow -1300,-1700,750` looks over the play from behind and to the side. Any
  other camera key turns it off until `0` (free camera) again. `--follow-team T` also keeps team T's
  car nearest to the ball in view: the camera looks at their midpoint, and the offset grows when they
  are more than 1500 uu apart (cars parked below the floor, z < -500, are ignored).
  `--follow-car ID` follows that car instead of the ball, with the offset turned so +x points from the
  car to the ball (y left, z up): `--follow 0,-900,250 --follow-car 1` watches the car from its side
  as it drives at the ball.
* **Several runs of one start, tiled**: `rlviz video plays.rlviz plays.mp4 [--speed 0.35]
  [--follow-team 0] [--labels "alone|vs bot 1"]` splits the replay wherever the tick doesn't advance by
  one (writers put runs one after the other with a gap), records each run headless with the follow
  camera, and tiles them (two side by side, more in a 2-column grid), all starting together and each
  holding its last frame. A run's last frame is skipped if it only clears the drawings. Renders on
  `$DISPLAY` (default `:99`, a virtual display such as Xvfb works).
* `rlviz wavedash game.rlviz` prints the counts, the landing -> jump press histogram (ticks) and the hop and cycle medians.
* **Many short runs, one after the other, slowed at moments**: `--sequence` chains the runs instead of
  tiling them. `--slow-wavedash` finds the landings after a dodge (the `wavedash` layer) and records at
  `--slow-speed` (0.25), keeping it slow for `--slow-window` (0.3) game seconds on each side of each
  landing and playing the rest at `--speed`, with a "slow 0.25x" mark:
  `rlviz video ep.rlviz ep.mp4 --sequence --speed 1 --slow-wavedash --follow 0,-900,250 --follow-car 1`.

Recording a live stream captures frames as they are rendered (not game-time exact); record the saved
replay instead when timing matters.

Cameras and the rest are RLViser's own: `1`–`8` follow the car with that id, `9` director camera,
`0` free camera (`WASD`, mouse, `Space`/`Ctrl` up/down, `Shift` faster), `Escape` frees the mouse
for the menus. The Menu window has ball cam and graphics settings (saved in `settings.txt`).

## Python package

| Module | What |
|---|---|
| `rlviz.format` | The stream format: `make_header`, `StreamWriter`, `ReplayWriter`, `read_replay` |
| `rlviz.draw` | Primitive constructors: `line`, `polyline`, `arrow`, `sphere`, `box`, `mesh`, `text`, `text2d`; surface and volume helpers `surface`, `heightfield`, `voxels`; `colormap`, colors |
| `rlviz.layers` | `Layer`, `DrawContext`, `Annotator` and the built-in layers |
| `rlviz.sinks` | `LiveSink` (TCP to the viewer, paced to game speed), `FileSink` |
| `rlviz.sim` | RocketSim fork → frames (`arena_header`, `arena_frame`), `run`, demo agents |
| `rlviz.cli` | `rlviz demo / annotate / info` |

Everything except `rlviz.sim` and the `ball_prediction` layer works without RocketSim.

### Running your own game

Agents are callables `agent(arena, car) -> RocketSim.CarControls`, so a policy, a scripted bot or a
planner plugs in the same way:

```python
from rlviz import sim, LiveSink, FileSink
from rlviz.layers import make_layers, DEFAULT_LAYERS

arena = sim.make_arena("soccar", blue=1, orange=1)
header = sim.arena_header(arena, names={1: "ppo-123", 2: "nexto"}, meta={"source": "my eval"})
agents = {1: my_policy_agent, 2: sim.ball_chase_agent()}
sinks = [LiveSink(header), FileSink(header, "eval.rlviz")]
try:
    sim.run(arena, agents, sinks, seconds=120, header=header, tick_skip=8,
            layers=make_layers(DEFAULT_LAYERS) + [MyPlanLayer()])
finally:
    for s in sinks:
        s.close()
```

RocketSim does not simulate the ball's rotation unless the arena is created with
`ArenaConfig(no_ball_rot=False)` (`sim.make_arena` does this). With the default the ball's `rot` stays
the identity and the ball does not spin in the viewer, which uses the rotation in the frames as is.

To record from other code (for example the training repo's evaluation), build frames with
`sim.arena_frame(arena)` (or by hand, see the format doc) and write them with `ReplayWriter`.
Frames can be written every tick or with a stride; the viewer plays them by tick number.

### Writing a layer

A layer turns the current frame (and the previous one) into primitives. It reads only frame dicts,
so the same layer works live and in `rlviz annotate`.

```python
from rlviz import Layer, draw

class TouchMarkers(Layer):
    name = "planner.touch"          # group name in the viewer; must be unique

    def __init__(self, plan_source):
        self.plan_source = plan_source

    def draw(self, ctx):
        plan = self.plan_source.plan_at(ctx.frame["tick"])
        if plan is None:
            return []               # clear the group
        return [draw.sphere(plan.contact, 20, draw.CYAN),
                draw.polyline(plan.car_path, draw.CYAN),
                draw.text(plan.contact, f"t={plan.time:.2f}s", draw.CYAN)]
```

* Return a list: the group as of this frame (`[]` clears it).
* Return `None`: no change; the viewer keeps the group from the last frame that had it. Use this to
  compute something expensive every N frames only (see `BallPrediction.every`).
* `ctx.frame`, `ctx.prev` (previous frame or `None`), `ctx.dt`, `ctx.index`, `ctx.header`,
  `ctx.prev_car(id)`, `ctx.car_header(id)`.

To make it selectable from the command line, add it to `LAYERS` in `rlviz/layers/__init__.py`, or
register it from your own module and pass `rlviz annotate --module my_layers`.

Layers that need data that is not in the frame (a policy's action distribution, a planner's plan)
are easiest to run inside your own loop, where that data exists: compute it, then call the layer or
put the group into `frame["draw"]` yourself before writing the frame.

### Surfaces and volumes

Filled shapes are `mesh` primitives; `rlviz.draw` builds the common ones:

```python
# a surface through a grid of points (e.g. a parametric surface sampled on u, v)
draw.surface([[f(u, v) for v in vs] for u in us], color=(1, 1, 1, 0.5))
# z = h(x, y), colored by another value (blue -> red over vrange)
draw.heightfield(xs, ys, h, color=(1, 1, 1, 0.6), value=time_to_reach, vrange=(0, 3))
# a volume as grid cells: only the outer faces are drawn, so a translucent color shows its shape
draw.voxels(origin, 80, [(i, j, k) for ... if reachable(i, j, k)], color=(0.8, 0.45, 1.0, 0.4))
# anything else: vertices and triangles, optional per-vertex colors
draw.mesh(points, triangles, colors=draw.colormap(values))
draw.box(center, size, rot=car["rot"])          # e.g. a hitbox; fill=True for a solid one
draw.sphere(center, r, draw.CYAN, fill=True)
```

Send a large surface or volume only when it changes (return `None` from the layer otherwise): the
viewer builds the mesh once per group version.

### Built-in layers

| Name | Shows |
|---|---|
| `ball_prediction` | Predicted ball path while the ball is in the air (ball-only RocketSim arena, cars ignored): points every 0.5 s and the first landing with its time |
| `vectors.vel` | Velocity arrows on the ball and cars (green, 0.25 s of travel) |
| `vectors.acc` | Acceleration (finite difference between frames, red, clamped to 600 uu) |
| `vectors.angvel` | Angular velocity axis (purple, 40 uu per rad/s) |
| `car_info` | Label above each car: name, boost, ground/air, J/DJ/F (jumped, double jumped, flipped), SS (supersonic), B (boosting) |
| `wavedash` | Landings after a dodge, from frame fields only (also works on real-game recordings): dodge point, path to the landing, dodge->landing ticks (wave dash if at most 30), nose angle at contact, ground speed and speed toward the ball before the dodge -> 3 ticks after landing, then ticks from the landing to the next jump press (rising edge of the jump control), hop apex above the height at the press and ticks to the next landing (full label on the latest 2 landings only); counter of wave dashes / air landings |

## In the real game (RLBot v5)

`rlviz.rlbot` runs the same layers on RLBot game packets and draws them in Rocket League with
RLBot's renderer (needs `pip install rlbot`; tested against `rlbot` 2.0.0b56). Packets become rlviz
frames (`packet_frame`, car ids = player index + 1, car body chosen by the closest hitbox), the
layers add their groups, and each changed group is sent as one RLBot render group (`rlviz:<name>`).

RLBot only draws lines, polylines and text (rectangles are screen-sized), so: `arrow` gets a
two-line head, `sphere` becomes three circles, `box` its 12 edges, `mesh` its outline (all edges
with `wire`, at most 2000), `fill` is ignored and filled surfaces can't be shown.

The match config must list the script (`[[scripts]]` with agent id `vlab/rlviz`) and allow
rendering (`enable_rendering = "OnByDefault"`; with `"OffByDefault"` the script asks for it). An
example match with two Psyonix bots is `/mnt/hdd0/rlbot-shared/rlviz/match.toml` (shared so the
`vlab` account running RLBotServer can read it). Then

    RLBOT_AGENT_ID=vlab/rlviz python -m rlviz.rlbot [--layers car_info,vectors.vel] [--out game.rlviz]

`--out` also saves the real game as a replay for the viewer. Checked in the game on v2 (2026-11-19):
labels, vectors and the ball prediction all show. A bot can call `packet_frame`,
`render_messages` and `group_id` itself to draw its own layers.

## Viewer internals

The rlviz code is in `src/rlviz/`:

* `format.rs`: serde types for the stream (`Header`, `Frame`, `Prim`);
* `source.rs`: reader threads for a file (zstd) and the TCP listener;
* `convert.rs`: rlviz frame → RLViser's `GameState`;
* `record.rs`: video recording (screenshots piped to ffmpeg);
* `solids.rs`: filled primitives (`mesh`, filled `box`/`sphere`) as mesh entities, rebuilt when their
  group changes;
* `mod.rs`: the `Timeline` resource, playback, recording control, the timeline/layers UI, gizmo and
  label drawing.

The frame under the cursor is pushed into RLViser's own update channel (`udp::UdpInjector`), so the
cars, ball, pads, cameras and interpolation are RLViser's unchanged code. Debug primitives are Bevy
gizmos on their own render layer (`camera::GIZMO_LAYER`, seen only by the 3D camera) plus egui labels
projected from world positions.

Changes to upstream files are small and marked in the history: the `bevy_gizmos_render` feature (in
Bevy 0.18 gizmos need it to be drawn at all), gizmos limited to the 3D camera, the `wayland` feature
dropped (no wayland headers on v2), `UdpInjector` and `UdpUpdate::Snap` (show a state exactly, without
interpolating from the previous one; used for seeking and recording), the `ApplyUdpUpdates` system set,
`calc_ball_rot` off by default (use the ball rotation from the frames), and the command line options
in `main.rs`.

Keep RL-specific logic out of the viewer: anything that needs to know what a policy, a reward or a
plan is belongs in a Python layer. The viewer should only learn new generic primitives.
