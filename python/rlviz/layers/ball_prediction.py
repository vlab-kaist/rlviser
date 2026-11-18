"""Predicted ball path while the ball is in the air, computed with the RocketSim fork.

The prediction ignores cars: it runs a ball-only arena (``Arena.get_ball_prediction``). It needs
``RocketSim`` to be importable and initialized with the collision meshes (``rlviz.sim.init``).
``RocketSim.BallPredictor`` is not used because it ignores the ``BallState`` passed from Python
(it predicts from the default kickoff ball; reported to the simulator session 2026-11-18).
"""

from __future__ import annotations

from .. import draw
from .base import DrawContext, Layer

BALL_RADIUS = {"soccar": 91.25, "hoops": 96.3831, "dropshot": 100.2565, "heatseeker": 91.25}


class BallPrediction(Layer):
    name = "ball_prediction"

    def __init__(self, seconds: float = 3.0, tick_interval: int = 2, every: int = 1,
                 marker_seconds: float = 0.5, only_airborne: bool = True, air_margin: float = 15.0):
        """``tick_interval``: ticks between path points. ``every``: recompute every N frames (the
        path stays on screen in between). ``marker_seconds``: a small sphere every this many seconds.
        ``only_airborne``: draw only when the ball is ``air_margin`` uu above resting height."""
        self.seconds = seconds
        self.tick_interval = tick_interval
        self.every = every
        self.marker_seconds = marker_seconds
        self.only_airborne = only_airborne
        self.air_margin = air_margin
        self._arena = None
        self._mode = None
        self._shown = False

    def reset(self) -> None:
        self._shown = False

    def _get_arena(self, ctx: DrawContext):
        import RocketSim as rs

        from .. import sim

        sim.init()
        mode = ctx.header["game_mode"]
        if self._arena is None or self._mode != mode:
            self._arena = rs.Arena(getattr(rs.GameMode, mode.upper(), rs.GameMode.SOCCAR), tick_rate=ctx.tick_rate)
            self._mode = mode
        return self._arena, rs

    def draw(self, ctx: DrawContext) -> list[dict] | None:
        ball = ctx.frame["ball"]
        radius = BALL_RADIUS.get(ctx.header["game_mode"], 91.25)
        airborne = ball["pos"][2] > radius + self.air_margin
        if self.only_airborne and not airborne:
            if self._shown:
                self._shown = False
                return []
            return None
        if self._shown and ctx.index % self.every:
            return None

        arena, rs = self._get_arena(ctx)
        state = rs.BallState()
        state.pos = rs.Vec(*ball["pos"])
        state.vel = rs.Vec(*ball["vel"])
        state.ang_vel = rs.Vec(*ball["ang_vel"])
        arena.ball.set_state(state)
        n = max(2, int(self.seconds * ctx.tick_rate / self.tick_interval))
        path = arena.get_ball_prediction(n, self.tick_interval)[1:]
        points = [ball["pos"]] + [s.pos.as_tuple() for s in path]

        prims = [draw.polyline(points, draw.YELLOW)]
        step = max(1, round(self.marker_seconds * ctx.tick_rate / self.tick_interval))
        for i in range(step, len(points), step):
            prims.append(draw.sphere(points[i], 8.0, draw.YELLOW))
        # where the ball first comes back down to the ground
        for i, p in enumerate(points[1:], 1):
            if p[2] < radius + 5.0:
                prims.append(draw.sphere(p, radius, (1.0, 0.9, 0.2, 0.6)))
                prims.append(draw.text(p, f"{i * self.tick_interval / ctx.tick_rate:.2f}s", draw.YELLOW))
                break
        self._shown = True
        return prims
