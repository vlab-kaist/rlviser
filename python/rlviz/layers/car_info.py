"""A label above each car: name, boost and state flags."""

from __future__ import annotations

from .. import draw
from .base import DrawContext, Layer


class CarInfo(Layer):
    name = "car_info"

    def __init__(self, height: float = 90.0, flags: bool = True):
        self.height = height
        self.flags = flags

    def draw(self, ctx: DrawContext) -> list[dict]:
        prims = []
        for car in ctx.frame["cars"]:
            info = ctx.car_header(car["id"])
            name = info.get("name") or f"car {car['id']}"
            lines = [name]
            if car.get("demoed"):
                lines.append("DEMOED")
            else:
                lines.append(f"boost {car.get('boost', 0):.0f}")
                if self.flags:
                    flags = ["ground" if car.get("on_ground") else "air"]
                    flags += [label for key, label in (("jumped", "J"), ("double_jumped", "DJ"),
                                                       ("flipped", "F"), ("supersonic", "SS"),
                                                       ("boosting", "B")) if car.get(key)]
                    lines.append(" ".join(flags))
            pos = car["pos"]
            color = draw.TEAM_COLORS[info.get("team", 0) & 1]
            prims.append(draw.text((pos[0], pos[1], pos[2] + self.height), "\n".join(lines), color))
        return prims
