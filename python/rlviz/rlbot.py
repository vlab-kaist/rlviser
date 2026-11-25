"""Debug layers in the real game: an RLBot v5 script that turns game packets into rlviz frames, runs
the same layers as for simulated games, and draws their groups with RLBot's renderer.

RLBot only draws lines, polylines, text and screen-sized rectangles, so the other primitives are
approximated: arrows get a two-line head, spheres become three circles, boxes their 12 edges and
meshes their outline (all edges with ``wire``). Filled surfaces can't be drawn in the game.

A group is sent again only when its layer returns new primitives (``None`` keeps the old one), and
RLBot keeps showing it until it is replaced, like the viewer. ``--out`` also saves the frames as a
``.rlviz`` replay of the real game.

The match must list the script and allow rendering (``enable_rendering = "OnByDefault"``, or
``"OffByDefault"`` and the script asks for it, which it does)::

    RLBOT_AGENT_ID=vlab/rlviz python -m rlviz.rlbot [--layers ...] [--out game.rlviz]

Needs the ``rlbot`` package (``pip install rlbot``), which nothing else in rlviz imports.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterable, Sequence

from rlbot import flat
from rlbot.managers import Script

from .format import Frame, Header, make_header
from .layers import DEFAULT_LAYERS, Annotator, make_layers

DEFAULT_AGENT_ID = "vlab/rlviz"
#: Group ids are namespaced so layer names can't collide with a bot's own render groups.
GROUP_PREFIX = "rlviz:"
#: Edges drawn for one mesh at most (a mesh's outline can be long).
MAX_MESH_EDGES = 2000
CIRCLE_SEGMENTS = 24
#: RLBot drops a message over 64 KiB; a bigger group keeps only its last primitives (leaving room
#: for the message's own framing).
MAX_GROUP_BYTES = 60000

MODES = {
    flat.GameMode.Soccar: "soccar",
    flat.GameMode.Hoops: "hoops",
    flat.GameMode.Dropshot: "dropshot",
    flat.GameMode.Snowday: "snowday",
}


# ---- packets -> frames ------------------------------------------------------------------------

def _v(v) -> list[float]:
    return [float(v.x), float(v.y), float(v.z)]


def rot_rows(r) -> list[float]:
    """RLBot Rotator (pitch, yaw, roll) -> rotation matrix rows forward, right, up (as RocketSim's
    ``rot_mat``, the convention of rlgym_compat)."""
    cp, cy, cr = math.cos(r.pitch), math.cos(r.yaw), math.cos(r.roll)
    sp, sy, sr = math.sin(r.pitch), math.sin(r.yaw), math.sin(r.roll)
    forward = [cp * cy, cp * sy, sp]
    right = [cy * sp * sr - cr * sy, sy * sp * sr + cr * cy, -cp * sr]
    up = [-cr * cy * sp - sr * sy, -cr * sy * sp + sr * cy, cp * cr]
    return forward + right + up


def _body(phys) -> dict:
    return {"pos": _v(phys.location), "vel": _v(phys.velocity), "ang_vel": _v(phys.angular_velocity),
            "rot": rot_rows(phys.rotation)}


def _car_config(hitbox) -> dict | None:
    """The RocketSim preset whose hitbox is closest to the car's (None without RocketSim)."""
    try:
        import RocketSim as rs

        from .sim import car_config
    except ImportError:
        return None
    size = (hitbox.length, hitbox.width, hitbox.height)
    presets = [rs.CarConfig(getattr(rs.CarConfig, p))
               for p in ("OCTANE", "DOMINUS", "PLANK", "BREAKOUT", "HYBRID", "MERC")]
    best = min(presets, key=lambda c: sum(abs(a - b) for a, b in zip(c.hitbox_size, size)))
    return car_config(best)


def packet_header(packet: flat.GamePacket, field: flat.FieldInfo, config: flat.MatchConfiguration) -> Header:
    cars = []
    for i, p in enumerate(packet.players):
        car = {"id": i + 1, "team": int(p.team), "name": p.name}
        cfg = _car_config(p.hitbox)
        if cfg is not None:
            car["config"] = cfg
        cars.append(car)
    pads = [{"pos": _v(pad.location), "big": bool(pad.is_full_boost)} for pad in field.boost_pads]
    return make_header(MODES.get(config.game_mode, "soccar"), pads=pads, cars=cars,
                       meta={"source": "rlbot", "map": config.game_map_upk})


def packet_frame(packet: flat.GamePacket) -> Frame:
    """One rlviz frame from a game packet. Car ids are player index + 1, as in :func:`packet_header`."""
    cars = []
    for i, p in enumerate(packet.players):
        c = p.last_input
        on_ground = p.air_state == flat.AirState.OnGround
        entry = _body(p.physics)
        entry.update({
            "id": i + 1,
            "boost": float(p.boost),
            "on_ground": on_ground,
            "wheels": [on_ground] * 4,
            "jumped": p.has_jumped,
            "double_jumped": p.has_double_jumped,
            "flipped": p.has_dodged,
            "demoed": p.demolished_timeout > 0,
            "supersonic": p.is_supersonic,
            "boosting": bool(c.boost) and p.boost > 0,
            "controls": [c.throttle, c.steer, c.pitch, c.yaw, c.roll,
                         float(c.jump), float(c.boost), float(c.handbrake)],
        })
        cars.append(entry)
    ball = _body(packet.balls[0].physics) if packet.balls else \
        {"pos": [0.0, 0.0, -1000.0], "vel": [0.0] * 3, "ang_vel": [0.0] * 3, "rot": [1, 0, 0, 0, 1, 0, 0, 0, 1]}
    return {
        "tick": int(packet.match_info.frame_num),
        "ball": ball,
        "cars": cars,
        "pads": [bool(s.is_active) for s in packet.boost_pads],
    }


# ---- primitives -> render messages ------------------------------------------------------------

def _color(c: Sequence[float]) -> flat.Color:
    return flat.Color(*(max(0, min(255, round(x * 255))) for x in c))


def _vec(p: Sequence[float]) -> flat.Vector3:
    return flat.Vector3(float(p[0]), float(p[1]), float(p[2]))


def _line(a, b, color) -> flat.RenderMessage:
    return flat.RenderMessage(flat.Line3D(flat.RenderAnchor(_vec(a)), flat.RenderAnchor(_vec(b)), color))


def _polyline(points, color) -> flat.RenderMessage:
    return flat.RenderMessage(flat.PolyLine3D([_vec(p) for p in points], color))


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _norm(a):
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return [x / n for x in a] if n > 1e-9 else None


def _arrow(a, b, color) -> list[flat.RenderMessage]:
    out = [_line(a, b, color)]
    d = _sub(b, a)
    length = math.sqrt(sum(x * x for x in d))
    if length < 1e-6:
        return out
    u = [x / length for x in d]
    side = _norm(_cross(u, [0, 0, 1])) or [1, 0, 0]
    head = min(0.25 * length, 60.0)
    for s in (1, -1):
        out.append(_line(b, [b[i] - u[i] * head + s * side[i] * head * 0.5 for i in range(3)], color))
    return out


def _sphere(c, r, color) -> list[flat.RenderMessage]:
    out = []
    for axes in ((0, 1), (0, 2), (1, 2)):
        pts = []
        for k in range(CIRCLE_SEGMENTS + 1):
            t = 2 * math.pi * k / CIRCLE_SEGMENTS
            p = list(c)
            p[axes[0]] += r * math.cos(t)
            p[axes[1]] += r * math.sin(t)
            pts.append(p)
        out.append(_polyline(pts, color))
    return out


def _box(c, size, rot, color) -> list[flat.RenderMessage]:
    rows = rot or [1, 0, 0, 0, 1, 0, 0, 0, 1]
    axes = [rows[0:3], rows[3:6], rows[6:9]]

    def corner(sx, sy, sz):
        return [c[i] + sx * axes[0][i] * size[0] / 2 + sy * axes[1][i] * size[1] / 2 + sz * axes[2][i] * size[2] / 2
                for i in range(3)]

    out = []
    for sz in (-1, 1):  # bottom and top rectangles
        out.append(_polyline([corner(-1, -1, sz), corner(1, -1, sz), corner(1, 1, sz), corner(-1, 1, sz),
                              corner(-1, -1, sz)], color))
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        out.append(_line(corner(sx, sy, -1), corner(sx, sy, 1), color))
    return out


def _mesh(v, tri, wire, color) -> list[flat.RenderMessage]:
    """All edges with ``wire``, else the outline (edges of one triangle only)."""
    count: dict[tuple[int, int], int] = {}
    for t in tri:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            key = (a, b) if a < b else (b, a)
            count[key] = count.get(key, 0) + 1
    edges = [e for e, n in count.items() if wire or n == 1]
    return [_line(v[a], v[b], color) for a, b in edges[:MAX_MESH_EDGES] if a < len(v) and b < len(v)]


def render_messages(prims: Iterable[dict]) -> list[flat.RenderMessage]:
    """rlviz primitives as RLBot render messages (unknown types are skipped)."""
    out: list[flat.RenderMessage] = []
    for p in prims:
        t = p.get("t")
        color = _color(p.get("color", (1, 1, 1, 1)))
        if t == "line":
            out.append(_line(p["a"], p["b"], color))
        elif t == "polyline":
            if len(p["pts"]) >= 2:
                out.append(_polyline(p["pts"], color))
        elif t == "arrow":
            out += _arrow(p["a"], p["b"], color)
        elif t == "sphere":
            out += _sphere(p["c"], p["r"], color)
        elif t == "box":
            out += _box(p["c"], p["size"], p.get("rot"), color)
        elif t == "mesh":
            out += _mesh(p["v"], p["tri"], p.get("wire", False), color)
        elif t == "text":
            out.append(flat.RenderMessage(flat.String3D(
                p["text"], flat.RenderAnchor(_vec(p["pos"])), 1.0, color, flat.Color(0, 0, 0, 120),
                flat.TextHAlign.Center, flat.TextVAlign.Bottom)))
        elif t == "text2d":
            x, y = p["pos"]
            out.append(flat.RenderMessage(flat.String2D(
                p["text"], float(x), float(y), 1.0, color, flat.Color(0, 0, 0, 120))))
    return out


def fit_group(msgs: list[flat.RenderMessage], gid: int) -> flat.RenderGroup:
    """``msgs`` as one render group, dropping the oldest (first) messages until it fits."""
    group = flat.RenderGroup(msgs, gid)
    if len(group.pack()) <= MAX_GROUP_BYTES:
        return group
    lo, hi = 0, len(msgs)  # smallest drop count that fits is in (lo, hi]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if len(flat.RenderGroup(msgs[mid:], gid).pack()) <= MAX_GROUP_BYTES:
            hi = mid
        else:
            lo = mid
    return flat.RenderGroup(msgs[hi:], gid)


def group_id(name: str) -> int:
    """RLBot render group id for an rlviz group name (stable across runs, unlike Python's hash)."""
    h = 2166136261
    for b in (GROUP_PREFIX + name).encode():
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h & 0x3FFFFFFF


# ---- the script -------------------------------------------------------------------------------

class LayerScript(Script):
    """Runs rlviz layers on every game packet and renders their groups in the game."""

    def __init__(self, layers: Sequence[str] = DEFAULT_LAYERS, out: str | None = None,
                 agent_id: str = DEFAULT_AGENT_ID):
        super().__init__(agent_id)
        self.layer_names = list(layers)
        self.out = out
        self.annotate: Annotator | None = None
        self.sink = None
        self.shown: set[str] = set()
        self.last_tick = -1

    def initialize(self):
        if not self.renderer.can_render:
            self.update_rendering_status(True)

    def _start(self, packet: flat.GamePacket):
        header = packet_header(packet, self.field_info, self.match_config)
        self.annotate = Annotator(header, make_layers(self.layer_names))
        if self.out:
            from .sinks import FileSink

            if self.sink is not None:
                self.sink.close()
            self.sink = FileSink(header, self.out)

    def handle_packet(self, packet: flat.GamePacket):
        if not packet.players:
            return
        tick = int(packet.match_info.frame_num)
        if tick == self.last_tick:
            return
        if self.annotate is None or len(packet.players) != len(self.annotate.header["cars"]):
            self._start(packet)
        self.last_tick = tick
        frame = self.annotate(packet_frame(packet))
        if self.sink is not None:
            self.sink.write(frame)
        for group in frame.get("draw", []):
            gid = group_id(group["name"])
            msgs = render_messages(group["prims"])
            if msgs:
                self._game_interface.send_msg(fit_group(msgs, gid))
                self.shown.add(group["name"])
            elif group["name"] in self.shown:
                self._game_interface.send_msg(flat.RemoveRenderGroup(gid))
                self.shown.discard(group["name"])

    def retire(self):
        if self.sink is not None:
            self.sink.close()


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--layers", default=",".join(DEFAULT_LAYERS), help="comma-separated layer names")
    p.add_argument("--out", help="also save the game as this .rlviz file")
    p.add_argument("--agent-id", default=DEFAULT_AGENT_ID,
                   help="agent id in the match config (RLBOT_AGENT_ID overrides it)")
    args = p.parse_args(argv)
    LayerScript([n for n in args.layers.split(",") if n], args.out, args.agent_id).run(
        wants_match_communications=False, wants_ball_predictions=False)


if __name__ == "__main__":
    main()
