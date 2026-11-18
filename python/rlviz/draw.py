"""Debug draw primitives (the ``prims`` of a frame's draw group).

Positions are Rocket League world coordinates (uu, z up). Colors are RGBA in 0..1.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

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


def sphere(center: Vec, radius: float, color: Color = WHITE, fill: bool = False) -> dict:
    """Wireframe ball, or a shaded solid one with ``fill``."""
    p = {"t": "sphere", "c": _v(center), "r": float(radius), "color": list(color)}
    if fill:
        p["fill"] = True
    return p


def box(center: Vec, size: Vec, color: Color = WHITE, rot: Sequence[float] | None = None,
        fill: bool = False) -> dict:
    """A box of full extents ``size`` (along forward, right, up). ``rot``: 9 floats, rotation
    matrix rows forward, right, up (as a body's ``rot``); default axis-aligned (x, y, z)."""
    p = {"t": "box", "c": _v(center), "size": _v(size), "color": list(color)}
    if rot is not None:
        p["rot"] = [float(x) for x in rot]
    if fill:
        p["fill"] = True
    return p


def mesh(vertices: Sequence[Vec], triangles: Iterable[Sequence[int]], color: Color = WHITE,
         colors: Sequence[Color] | None = None, wire: bool = False) -> dict:
    """Shaded triangles (a surface, or the boundary of a volume), seen from both sides.
    ``colors``: one per vertex, replaces ``color`` (see ``colormap``). Alpha < 1 is translucent.
    ``wire`` also draws the edges."""
    p = {"t": "mesh", "v": [_v(q) for q in vertices], "tri": [[int(i) for i in t] for t in triangles],
         "color": list(color)}
    if colors is not None:
        p["colors"] = [list(c) for c in colors]
    if wire:
        p["wire"] = True
    return p


def surface(grid: Sequence[Sequence[Vec]], color: Color = WHITE,
            colors: Sequence[Sequence[Color]] | None = None, wire: bool = False) -> dict:
    """A surface through a grid of points ``grid[i][j]`` (rows of equal length), e.g. a
    parametric surface sampled on (u, v). ``colors[i][j]``: per point, optional."""
    rows, cols = len(grid), len(grid[0])
    vertices = [q for row in grid for q in row]
    tris = []
    for i in range(rows - 1):
        for j in range(cols - 1):
            a, b, c, d = i * cols + j, i * cols + j + 1, (i + 1) * cols + j, (i + 1) * cols + j + 1
            tris += [(a, b, d), (a, d, c)]
    flat = None if colors is None else [c for row in colors for c in row]
    return mesh(vertices, tris, color, flat, wire)


def heightfield(xs: Sequence[float], ys: Sequence[float], z: Callable[[float, float], float],
                color: Color = WHITE, value: Callable[[float, float], float] | None = None,
                vrange: tuple[float, float] | None = None, wire: bool = False) -> dict:
    """The surface ``z(x, y)`` over the grid ``xs`` x ``ys``. With ``value`` (and ``vrange``) the
    surface is colored by ``value(x, y)`` through ``colormap``."""
    grid = [[(x, y, z(x, y)) for y in ys] for x in xs]
    colors = None
    if value is not None:
        vals = [[value(x, y) for y in ys] for x in xs]
        flat = colormap([v for row in vals for v in row], *(vrange or (None, None)), alpha=color[3])
        colors = [flat[i * len(ys):(i + 1) * len(ys)] for i in range(len(xs))]
    return surface(grid, color, colors, wire)


def voxels(origin: Vec, cell: float | Vec, occupied: Iterable[tuple[int, int, int]], color: Color = WHITE,
           wire: bool = False) -> dict:
    """A volume made of grid cells: ``occupied`` lists the (i, j, k) cells inside it, cell (i, j, k)
    spans ``origin + (i, j, k) * cell`` to ``+ cell``. Only the outer faces are drawn, so a
    translucent color shows the volume's shape (e.g. a reachable or feasible region)."""
    cx, cy, cz = (cell, cell, cell) if isinstance(cell, (int, float)) else cell
    cells = set(map(tuple, occupied))
    vertices: list[tuple[float, float, float]] = []
    index: dict[tuple[int, int, int], int] = {}
    tris = []

    def vid(i: int, j: int, k: int) -> int:
        key = (i, j, k)
        if key not in index:
            index[key] = len(vertices)
            vertices.append((origin[0] + i * cx, origin[1] + j * cy, origin[2] + k * cz))
        return index[key]

    # each face: neighbour offset and its 4 corners (as offsets of the cell's low corner)
    faces = (
        ((-1, 0, 0), ((0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1))),
        ((1, 0, 0), ((1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0))),
        ((0, -1, 0), ((0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0))),
        ((0, 1, 0), ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1))),
        ((0, 0, -1), ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))),
        ((0, 0, 1), ((0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1))),
    )
    for (i, j, k) in cells:
        for (di, dj, dk), corners in faces:
            if (i + di, j + dj, k + dk) in cells:
                continue
            a, b, c, d = (vid(i + oi, j + oj, k + ok) for oi, oj, ok in corners)
            tris += [(a, b, c), (a, c, d)]
    return mesh(vertices, tris, color, None, wire)


def colormap(values: Sequence[float], vmin: float | None = None, vmax: float | None = None,
             alpha: float = 1.0) -> list[Color]:
    """Colors for values on a blue → green → yellow → red ramp over [vmin, vmax] (default: the
    values' range)."""
    vals = [float(v) for v in values]
    lo = min(vals) if vmin is None else vmin
    hi = max(vals) if vmax is None else vmax
    stops = ((0.2, 0.3, 1.0), (0.2, 0.9, 0.4), (1.0, 0.9, 0.2), (1.0, 0.25, 0.2))
    out = []
    for v in vals:
        t = 0.0 if hi <= lo else min(max((v - lo) / (hi - lo), 0.0), 1.0)
        s = t * (len(stops) - 1)
        n = min(int(s), len(stops) - 2)
        f = s - n
        a, b = stops[n], stops[n + 1]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, alpha))
    return out


def text(pos: Vec, s: str, color: Color = WHITE) -> dict:
    """A label anchored at a world position (drawn above it)."""
    return {"t": "text", "pos": _v(pos), "text": s, "color": list(color)}


def text2d(x: float, y: float, s: str, color: Color = WHITE) -> dict:
    """A label at a screen position given as fractions of the window, from the top left."""
    return {"t": "text2d", "pos": [float(x), float(y)], "text": s, "color": list(color)}
