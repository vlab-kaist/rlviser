"""Debug draw primitives (the ``prims`` of a frame's draw group).

Positions are Rocket League world coordinates (uu, z up). Colors are RGBA in 0..1.
"""

from __future__ import annotations

from typing import Sequence

Vec = Sequence[float]
Color = tuple[float, float, float, float]

WHITE: Color = (1.0, 1.0, 1.0, 1.0)
BLUE: Color = (0.25, 0.55, 1.0, 1.0)
ORANGE: Color = (1.0, 0.55, 0.1, 1.0)
GREEN: Color = (0.3, 1.0, 0.4, 1.0)
YELLOW: Color = (1.0, 0.9, 0.2, 1.0)
RED: Color = (1.0, 0.3, 0.3, 1.0)
PURPLE: Color = (0.8, 0.45, 1.0, 1.0)
CYAN: Color = (0.3, 0.95, 1.0, 1.0)
TEAM_COLORS = (BLUE, ORANGE)


def _v(p: Vec) -> list[float]:
    return [float(p[0]), float(p[1]), float(p[2])]


def line(a: Vec, b: Vec, color: Color = WHITE) -> dict:
    return {"t": "line", "a": _v(a), "b": _v(b), "color": list(color)}


def polyline(points: Sequence[Vec], color: Color = WHITE) -> dict:
    return {"t": "polyline", "pts": [_v(p) for p in points], "color": list(color)}


def arrow(a: Vec, b: Vec, color: Color = WHITE) -> dict:
    return {"t": "arrow", "a": _v(a), "b": _v(b), "color": list(color)}


def sphere(center: Vec, radius: float, color: Color = WHITE) -> dict:
    return {"t": "sphere", "c": _v(center), "r": float(radius), "color": list(color)}


def text(pos: Vec, s: str, color: Color = WHITE) -> dict:
    """A label anchored at a world position (drawn above it)."""
    return {"t": "text", "pos": _v(pos), "text": s, "color": list(color)}


def text2d(x: float, y: float, s: str, color: Color = WHITE) -> dict:
    """A label at a screen position given as fractions of the window, from the top left."""
    return {"t": "text2d", "pos": [float(x), float(y)], "text": s, "color": list(color)}
