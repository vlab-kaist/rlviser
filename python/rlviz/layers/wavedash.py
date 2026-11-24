"""Wave dashes: a dodge that ends in a landing, the landing cancelling the flip.

Found from frame fields only (``flipped``, ``on_ground``, ``rot``, ``vel``), so the same layer works on
simulated games and on real-game recordings (``rlviz.rlbot --out``). A dodge starts on the frame where
``flipped`` turns on in the air; a landing is the frame where ``on_ground`` turns on. A landing whose
dodge started at most ``max_ticks`` before it is a wave dash.

Drawn for each landing of the current run: the dodge point (orange), the car's path from there to the
landing (yellow for a wave dash, grey otherwise) and a label at the landing point: dodge -> landing
ticks, the nose angle at contact (+ nose up), and the ground speed and the speed toward the ball from
just before the dodge to ``after_ticks`` after the landing. Once known, the label also gets what
followed the landing: ticks to the next jump press (the rising edge of the jump control), the height
of that hop's apex above the car's height at the press, and the cycle length (ticks to the next landing). Only the
latest ``full_labels`` landings keep the full label; older ones are shortened, so chained dashes
stay readable. While a dodge is in the air, the car shows
how many ticks ago it dodged. A 2D line counts the wave dashes and air landings so far. Markers are
cleared when a new run starts (the tick does not advance by one).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import draw
from .base import DrawContext, Layer

GREY = (0.6, 0.6, 0.6, 1.0)


def _ground_speed(car) -> float:
    return math.hypot(car["vel"][0], car["vel"][1])


def _toward_ball(car, ball) -> float:
    dx, dy = ball["pos"][0] - car["pos"][0], ball["pos"][1] - car["pos"][1]
    d = math.hypot(dx, dy) or 1.0
    return (car["vel"][0] * dx + car["vel"][1] * dy) / d


def _nose(car) -> float:
    """Pitch of the car's forward axis in degrees, + nose up."""
    return math.degrees(math.asin(max(-1.0, min(1.0, car["rot"][2]))))


def _dodge_dir(controls) -> str:
    if not controls:
        return ""
    pitch, yaw = -controls[2], controls[3]  # pitch -1 dodges forward
    parts = (["front"] if pitch > 0.3 else ["back"] if pitch < -0.3 else []) + \
            (["right"] if yaw > 0.3 else ["left"] if yaw < -0.3 else [])
    return "-".join(parts) or "neutral"


@dataclass
class Landing:
    car_id: int
    tick: int
    pos: list
    path: list
    dodge_tick: int | None = None
    dodge_pos: list | None = None
    dodge_dir: str = ""
    nose: float = 0.0
    speed_before: float = 0.0
    toward_before: float = 0.0
    speed_after: float | None = None
    toward_after: float | None = None
    press_z: float | None = None
    jump_ticks: int | None = None
    apex: float | None = None
    cycle: int | None = None

    def ticks(self) -> int | None:
        return None if self.dodge_tick is None else self.tick - self.dodge_tick


@dataclass
class _Car:
    air: bool = False
    flipped: bool = False
    dodge_tick: int | None = None
    dodge_pos: list | None = None
    dodge_dir: str = ""
    before: tuple = (0.0, 0.0)
    path: list = field(default_factory=list)
    press: bool = False
    last: Landing | None = None


class WaveDash(Layer):
    name = "wavedash"

    def __init__(self, max_ticks: int = 30, after_ticks: int = 3, full_labels: int = 2):
        self.max_ticks = max_ticks
        self.after_ticks = after_ticks
        self.full_labels = full_labels
        self.reset()

    def reset(self) -> None:
        self.cars: dict[int, _Car] = {}
        self.landings: list[Landing] = []  # this run
        self.all: list[Landing] = []
        self.wavedashes = 0
        self.air_landings = 0

    def is_wavedash(self, landing: Landing) -> bool:
        t = landing.ticks()
        return t is not None and t <= self.max_ticks

    def draw(self, ctx: DrawContext) -> list[dict]:
        frame, tick = ctx.frame, ctx.frame["tick"]
        if ctx.prev is not None and tick != ctx.prev["tick"] + 1:  # new run
            self.cars, self.landings = {}, []
        ball = frame["ball"]
        prims = []
        for car in frame["cars"]:
            if car.get("demoed"):
                continue
            st = self.cars.setdefault(car["id"], _Car(air=not car.get("on_ground", True)))
            prev = ctx.prev_car(car["id"]) if ctx.prev is not None and tick == ctx.prev["tick"] + 1 else None
            on_ground, flipped = car.get("on_ground", True), car.get("flipped", False)
            controls = car.get("controls")
            press, last, z = bool(controls) and controls[5] > 0.5, st.last, car["pos"][2]
            if last is not None and last.cycle is None:  # what follows the latest landing
                if press and not st.press and last.jump_ticks is None:
                    last.jump_ticks, last.press_z = tick - last.tick, z
                if last.press_z is not None:
                    last.apex = max(last.apex or 0.0, z - last.press_z)
            if not on_ground:
                if not st.air:
                    st.air, st.dodge_tick, st.path = True, None, []
                if flipped and not st.flipped:
                    src = prev or car
                    st.dodge_tick, st.dodge_pos = tick, list(car["pos"])
                    st.dodge_dir = _dodge_dir(src.get("controls"))
                    st.before = (_ground_speed(src), _toward_ball(src, ball))
                    st.path = [list(car["pos"])]
                elif st.dodge_tick is not None:
                    st.path.append(list(car["pos"]))
                    prims.append(draw.text(car["pos"], f"dodged {tick - st.dodge_tick} ticks ago", draw.YELLOW))
            elif st.air:  # landing
                st.air = False
                landing = Landing(car["id"], tick, list(car["pos"]), st.path + [list(car["pos"])], st.dodge_tick,
                                  st.dodge_pos, st.dodge_dir, _nose(car), *st.before)
                if st.last is not None and st.last.cycle is None:
                    st.last.cycle = tick - st.last.tick
                st.last = landing
                self.landings.append(landing)
                self.all.append(landing)
                self.air_landings += 1
                self.wavedashes += self.is_wavedash(landing)
                st.dodge_tick, st.path = None, []
            st.flipped, st.press = flipped, press
            for landing in self.landings:
                if landing.car_id == car["id"] and landing.speed_after is None \
                        and tick - landing.tick >= self.after_ticks:
                    landing.speed_after, landing.toward_after = _ground_speed(car), _toward_ball(car, ball)

        for k, landing in enumerate(self.landings):
            prims += self._landing_prims(landing, full=k >= len(self.landings) - self.full_labels)
        prims.append(draw.text2d(0.01, 0.92, f"wave dashes {self.wavedashes} / air landings {self.air_landings}",
                                 draw.YELLOW))
        return prims

    def _landing_prims(self, landing: Landing, full: bool = True) -> list[dict]:
        wave = self.is_wavedash(landing)
        color = draw.YELLOW if wave else GREY
        prims = [draw.sphere(landing.pos, 40, draw.WHITE)]
        if landing.dodge_pos is not None:
            prims.append(draw.sphere(landing.dodge_pos, 30, draw.ORANGE))
            if full:
                prims.append(draw.text(landing.dodge_pos, f"dodge ({landing.dodge_dir})", draw.ORANGE))
            if len(landing.path) > 1:
                prims.append(draw.polyline(landing.path, color))
        if not full:
            short = f"WD {landing.ticks()}t" if wave else "landing"
            prims.append(draw.text([landing.pos[0], landing.pos[1], landing.pos[2] + 60], short, color))
            return prims
        if wave:
            head = f"WAVE DASH  dodge->land {landing.ticks()} ticks"
        elif landing.dodge_tick is not None:
            head = f"landing, dodge {landing.ticks()} ticks before"
        else:
            head = "landing, no dodge"
        lines = [head, f"nose {landing.nose:+.0f} deg at contact"]
        if landing.speed_after is not None:
            lines.append(f"speed {landing.speed_before:.0f} -> {landing.speed_after:.0f}"
                         f"  toward ball {landing.toward_after - landing.toward_before:+.0f}")
        after = []
        if landing.jump_ticks is not None:
            after.append(f"jump +{landing.jump_ticks} ticks")
        if landing.apex is not None and landing.cycle is not None:
            after.append(f"hop {landing.apex:.0f} uu")
        if landing.cycle is not None:
            after.append(f"next landing +{landing.cycle} ticks")
        if after:
            lines.append(", ".join(after))
        prims.append(draw.text([landing.pos[0], landing.pos[1], landing.pos[2] + 120], "\n".join(lines), color))
        return prims


def landings(header, frames, **kw) -> list[Landing]:
    """All landings in a replay (wave dash or not), e.g. to slow a video down around them."""
    layer = WaveDash(**kw)
    from .base import Annotator

    annotate = Annotator(header, [layer])
    for frame in frames:
        annotate(dict(frame, draw=[]))
    return layer.all


def stats(landings_: list[Landing], max_ticks: int = 30) -> dict:
    """Counts and the landing -> jump press histogram (ticks) of :func:`landings`' output."""
    import statistics

    def med(xs):
        return statistics.median(xs) if xs else None

    hist: dict[int, int] = {}
    for land in landings_:
        if land.jump_ticks is not None:
            hist[land.jump_ticks] = hist.get(land.jump_ticks, 0) + 1
    jumped = [land for land in landings_ if land.jump_ticks is not None and land.cycle is not None]
    return {
        "landings": len(landings_),
        "wavedashes": sum(1 for land in landings_ if land.ticks() is not None and land.ticks() <= max_ticks),
        "landing_to_press": dict(sorted(hist.items())),
        "landing_to_press_median": med([land.jump_ticks for land in landings_ if land.jump_ticks is not None]),
        "hop_median": med([land.apex for land in jumped]),
        "cycle_median": med([land.cycle for land in jumped]),
    }
