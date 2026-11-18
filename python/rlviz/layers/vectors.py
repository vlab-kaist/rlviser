"""Velocity, acceleration and angular velocity arrows on the ball and the cars."""

from __future__ import annotations

import math

from .. import draw
from .base import DrawContext, Layer

# quantity -> (scale: arrow uu per unit, max arrow length uu, color)
QUANTITIES = {
    "vel": (0.25, 800.0, draw.GREEN),  # uu/s; 2300 uu/s -> 575 uu
    "acc": (0.1, 600.0, draw.RED),  # uu/s^2, finite difference of vel between frames
    "angvel": (40.0, 400.0, draw.PURPLE),  # rad/s; 5.5 rad/s -> 220 uu
}


def _scaled(origin, vec, scale: float, max_len: float):
    x, y, z = (v * scale for v in vec)
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1.0:
        return None
    if length > max_len:
        x, y, z = (v * max_len / length for v in (x, y, z))
    return [origin[0] + x, origin[1] + y, origin[2] + z]


class Vectors(Layer):
    """One quantity (``vel``, ``acc`` or ``angvel``) as arrows from the centers of the ball and cars."""

    def __init__(self, quantity: str = "vel", ball: bool = True, cars: bool = True,
                 scale: float | None = None):
        if quantity not in QUANTITIES:
            raise ValueError(f"quantity must be one of {list(QUANTITIES)}")
        self.quantity = quantity
        self.name = f"vectors.{quantity}"
        default_scale, self.max_len, self.color = QUANTITIES[quantity]
        self.scale = default_scale if scale is None else scale
        self.ball = ball
        self.cars = cars

    def _value(self, body: dict, prev: dict | None, dt: float | None):
        if self.quantity == "vel":
            return body["vel"]
        if self.quantity == "angvel":
            return body["ang_vel"]
        if prev is None or dt is None:
            return None
        return [(a - b) / dt for a, b in zip(body["vel"], prev["vel"])]

    def draw(self, ctx: DrawContext) -> list[dict]:
        bodies = []
        if self.ball:
            bodies.append((ctx.frame["ball"], ctx.prev["ball"] if ctx.prev else None))
        if self.cars:
            bodies += [(car, ctx.prev_car(car["id"])) for car in ctx.frame["cars"] if not car.get("demoed")]

        prims = []
        for body, prev in bodies:
            value = self._value(body, prev, ctx.dt)
            if value is None:
                continue
            tip = _scaled(body["pos"], value, self.scale, self.max_len)
            if tip is not None:
                prims.append(draw.arrow(body["pos"], tip, self.color))
        return prims
