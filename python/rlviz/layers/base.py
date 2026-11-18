"""Layer interface: turn frames into debug draw groups.

A layer looks at the current frame (and the previous one, for differences) and returns primitives
from :mod:`rlviz.draw`. Layers only read frame dicts, so the same layer works while a simulation runs
and when annotating a saved replay (``rlviz annotate``).

Return value of :meth:`Layer.draw`:

* a list of primitives: the group shown from this frame on (an empty list clears it);
* ``None``: no change, the viewer keeps showing the group from an earlier frame. Use this to
  recompute expensive things every few ticks only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..format import Frame, Header


@dataclass
class DrawContext:
    header: Header
    frame: Frame
    prev: Frame | None
    """The frame before ``frame`` in the stream, or None at the start."""
    index: int
    """Position of ``frame`` in the stream."""

    @property
    def tick_rate(self) -> float:
        return self.header["tick_rate"]

    @property
    def dt(self) -> float | None:
        """Seconds since the previous frame."""
        if self.prev is None or self.prev["tick"] >= self.frame["tick"]:
            return None
        return (self.frame["tick"] - self.prev["tick"]) / self.tick_rate

    def prev_car(self, car_id: int) -> dict | None:
        if self.prev is None:
            return None
        return next((c for c in self.prev["cars"] if c["id"] == car_id), None)

    def car_header(self, car_id: int) -> dict[str, Any]:
        return next((c for c in self.header.get("cars", []) if c["id"] == car_id), {"id": car_id, "team": 0})


class Layer:
    #: Group name shown in the viewer's layer list. Must be unique among the layers in use.
    name: str = "layer"

    def draw(self, ctx: DrawContext) -> list[dict] | None:
        raise NotImplementedError

    def reset(self) -> None:
        """Called when a new stream starts."""


class Annotator:
    """Runs layers over a stream of frames and adds their groups to ``frame["draw"]``."""

    def __init__(self, header: Header, layers: list[Layer]):
        names = [layer.name for layer in layers]
        if len(set(names)) != len(names):
            raise ValueError(f"layer names must be unique: {names}")
        self.header = header
        self.layers = layers
        self._prev: Frame | None = None
        self._index = 0
        for layer in layers:
            layer.reset()

    def __call__(self, frame: Frame) -> Frame:
        ctx = DrawContext(self.header, frame, self._prev, self._index)
        groups = [g for g in frame.get("draw", []) if g["name"] not in {layer.name for layer in self.layers}]
        for layer in self.layers:
            prims = layer.draw(ctx)
            if prims is not None:
                groups.append({"name": layer.name, "prims": prims})
        if groups:
            frame["draw"] = groups
        else:
            frame.pop("draw", None)
        self._prev = frame
        self._index += 1
        return frame
