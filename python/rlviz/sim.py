"""Run games on the RocketSim fork and turn its state into rlviz frames.

Uses the fork's Python bindings (``import RocketSim``, the mtheall-style API). Agents are plain
callables ``agent(arena, car) -> RocketSim.CarControls``, so a policy, a scripted bot or a planner
can be plugged in the same way.
"""

from __future__ import annotations

import math
import os
import random
from pathlib import Path
from typing import Callable, Iterable, Protocol

import RocketSim as rs

from .format import Frame, Header, make_header
from .layers import Annotator, Layer

DEFAULT_MESHES = Path(__file__).resolve().parents[3] / "collision_meshes"
_initialized = False


def init(meshes: str | Path | None = None) -> None:
    """Loads the collision meshes once (``RLVIZ_COLLISION_MESHES`` or ``../collision_meshes``)."""
    global _initialized
    if not _initialized:
        rs.init(str(meshes or os.environ.get("RLVIZ_COLLISION_MESHES", DEFAULT_MESHES)))
        _initialized = True


MODE_NAMES = {
    rs.GameMode.SOCCAR: "soccar",
    rs.GameMode.HOOPS: "hoops",
    rs.GameMode.HEATSEEKER: "heatseeker",
    rs.GameMode.SNOWDAY: "snowday",
    rs.GameMode.DROPSHOT: "dropshot",
    rs.GameMode.THE_VOID: "void",
}


def _t(v) -> list[float]:
    return list(v.as_tuple())


def car_config(config) -> dict:
    """A ``RocketSim.CarConfig`` as the header's ``config`` map."""

    def wheels(w):
        return {"radius": w.wheel_radius, "suspension_rest": w.suspension_rest_length,
                "offset": _t(w.connection_point_offset)}

    return {
        "hitbox_size": _t(config.hitbox_size),
        "hitbox_offset": _t(config.hitbox_pos_offset),
        "front_wheels": wheels(config.front_wheels),
        "back_wheels": wheels(config.back_wheels),
        "dodge_deadzone": config.dodge_deadzone,
    }


def arena_header(arena, names: dict[int, str] | None = None, meta: dict | None = None) -> Header:
    names = names or {}
    cars = []
    counts = [0, 0]
    for car in arena.get_cars():
        team = int(car.team)
        counts[team] += 1
        cars.append({
            "id": car.id,
            "team": team,
            "name": names.get(car.id, f"{('blue', 'orange')[team]} {counts[team]}"),
            "config": car_config(car.get_config()),
        })
    pads = [{"pos": _t(pad.get_pos()), "big": bool(pad.is_big)} for pad in arena.get_boost_pads()]
    return make_header(MODE_NAMES[arena.game_mode], tick_rate=arena.tick_rate, pads=pads, cars=cars, meta=meta)


def _body(state) -> dict:
    rot = state.rot_mat
    return {
        "pos": _t(state.pos),
        "vel": _t(state.vel),
        "ang_vel": _t(state.ang_vel),
        "rot": _t(rot.forward) + _t(rot.right) + _t(rot.up),
    }


def arena_frame(arena) -> Frame:
    cars = []
    for car in arena.get_cars():
        s = car.get_state()
        c = s.last_controls
        entry = _body(s)
        entry.update({
            "id": car.id,
            "boost": s.boost,
            "on_ground": s.is_on_ground,
            "wheels": [bool(w) for w in s.wheels_with_contact],
            "jumped": s.has_jumped,
            "double_jumped": s.has_double_jumped,
            "flipped": s.has_flipped,
            "demoed": s.is_demoed,
            "supersonic": s.is_supersonic,
            "boosting": c.boost and s.boost > 0,
            "controls": [c.throttle, c.steer, c.pitch, c.yaw, c.roll,
                         float(c.jump), float(c.boost), float(c.handbrake)],
        })
        cars.append(entry)
    return {
        "tick": arena.tick_count,
        "ball": _body(arena.ball.get_state()),
        "cars": cars,
        "pads": [pad.get_state().is_active for pad in arena.get_boost_pads()],
    }


class Sink(Protocol):
    def write(self, frame: Frame) -> None: ...

    def close(self) -> None: ...


Agent = Callable[..., "rs.CarControls"]


def run(
    arena,
    agents: dict[int, Agent],
    sinks: Iterable[Sink],
    *,
    seconds: float,
    header: Header,
    layers: Iterable[Layer] = (),
    tick_skip: int = 8,
    frame_stride: int = 1,
    reset_on_goal: bool = True,
    seed: int | None = None,
) -> int:
    """Steps ``arena`` for ``seconds`` and sends a frame every ``frame_stride`` ticks to each sink.

    Agents are asked for controls every ``tick_skip`` ticks (cars without an agent keep their
    controls). After a goal the arena is reset to a kickoff. Returns the number of frames sent.
    """
    sinks = list(sinks)
    annotate = Annotator(header, list(layers))
    rng = random.Random(seed)
    scored = []
    if reset_on_goal:
        arena.set_goal_score_callback(lambda arena, scoring_team, data: scored.append(scoring_team))

    cars = {car.id: car for car in arena.get_cars()}
    total = int(seconds * arena.tick_rate)
    sent = 0
    for t in range(total):
        if t % tick_skip == 0:
            for car_id, agent in agents.items():
                cars[car_id].set_controls(agent(arena, cars[car_id]))
        arena.step(1)
        if scored:
            scored.clear()
            arena.reset_kickoff(rng.randrange(1 << 30))
        if t % frame_stride == 0:
            frame = annotate(arena_frame(arena))
            for sink in sinks:
                sink.write(frame)
            sent += 1
    return sent


# --- simple scripted agents, for demos and tests -------------------------------------------------


def idle_agent(arena, car):
    return rs.CarControls()


def ball_chase_agent(jump_height: float = 300.0, boost: bool = True):
    """Drives at the ball; jumps when the ball is above ``jump_height`` and close. Good enough to
    produce touches and airborne balls for testing layers, not a real bot."""

    def agent(arena, car):
        s = car.get_state()
        ball = arena.ball.get_state()
        dx, dy = ball.pos.x - s.pos.x, ball.pos.y - s.pos.y
        fwd = s.rot_mat.forward
        angle = math.atan2(dy, dx) - math.atan2(fwd.y, fwd.x)
        angle = (angle + math.pi) % (2 * math.pi) - math.pi
        c = rs.CarControls()
        c.throttle = 1.0
        c.steer = max(-1.0, min(1.0, 3.0 * angle))
        c.boost = boost and abs(angle) < 0.3
        c.handbrake = abs(angle) > 1.8
        dist = math.hypot(dx, dy)
        if s.is_on_ground and ball.pos.z > jump_height and dist < 600:
            c.jump = True
        elif not s.is_on_ground:
            c.jump = s.has_jumped and not s.has_double_jumped and dist < 250
            c.pitch = -1.0 if c.jump else 0.0
        return c

    return agent


def make_arena(game_mode: str = "soccar", blue: int = 1, orange: int = 1, seed: int | None = None):
    """An arena with ``blue`` + ``orange`` Octanes at a kickoff position.

    Ball rotation is simulated (RocketSim skips it by default, ``no_ball_rot=True``, and then the
    ball's ``rot`` stays the identity, so the ball would not spin in the viewer).
    """
    init()
    arena = rs.Arena(getattr(rs.GameMode, game_mode.upper()), config=rs.ArenaConfig(no_ball_rot=False))
    for _ in range(blue):
        arena.add_car(rs.Team.BLUE)
    for _ in range(orange):
        arena.add_car(rs.Team.ORANGE)
    arena.reset_kickoff(-1 if seed is None else seed)
    return arena
