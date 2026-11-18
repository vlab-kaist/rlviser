"""Debug layers. To add one, subclass :class:`Layer` (see ``base.py``) and register it in ``LAYERS``
if it should be selectable by name from the command line."""

from .ball_prediction import BallPrediction
from .base import Annotator, DrawContext, Layer
from .car_info import CarInfo
from .vectors import Vectors

#: Name -> factory, for ``--layers`` on the command line.
LAYERS = {
    "ball_prediction": BallPrediction,
    "vectors.vel": lambda: Vectors("vel"),
    "vectors.acc": lambda: Vectors("acc"),
    "vectors.angvel": lambda: Vectors("angvel"),
    "car_info": CarInfo,
}

DEFAULT_LAYERS = ("ball_prediction", "vectors.vel", "vectors.acc", "vectors.angvel", "car_info")


def make_layers(names) -> list[Layer]:
    unknown = [n for n in names if n not in LAYERS]
    if unknown:
        raise ValueError(f"unknown layers {unknown}; available: {sorted(LAYERS)}")
    return [LAYERS[n]() for n in names]


__all__ = ["Annotator", "BallPrediction", "CarInfo", "DrawContext", "Layer", "LAYERS", "DEFAULT_LAYERS",
           "Vectors", "make_layers"]
