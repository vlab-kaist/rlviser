import pytest

from rlviz import Annotator, Layer, ReplayWriter, draw, make_header, read_replay
from rlviz.layers import CarInfo, Vectors


def frame(tick, ball_z=93.0, vel=(0.0, 0.0, 0.0)):
    body = {"pos": [0.0, 0.0, ball_z], "vel": list(vel), "ang_vel": [0.0, 0.0, 1.0],
            "rot": [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]}
    car = dict(body, id=1, boost=33.0, on_ground=True, pos=[100.0, 0.0, 17.0])
    return {"tick": tick, "ball": body, "cars": [car], "pads": []}


def header():
    return make_header("soccar", cars=[{"id": 1, "team": 1, "name": "bot", "config": {}}])


def test_roundtrip(tmp_path):
    path = tmp_path / "a.rlviz"
    frames = [frame(t) for t in range(10)]
    frames[3]["draw"] = [{"name": "g", "prims": [draw.arrow((0, 0, 0), (1, 2, 3), draw.RED)]}]
    with ReplayWriter(path, header()) as w:
        for f in frames:
            w.write(f)
    h, back = read_replay(path)
    assert h["game_mode"] == "soccar" and len(back) == 10
    prim = back[3]["draw"][0]["prims"][0]  # floats come back as float32
    assert prim["t"] == "arrow" and prim["b"] == [1, 2, 3]
    assert prim["color"] == pytest.approx(list(draw.RED))


def test_bad_mode():
    with pytest.raises(ValueError):
        make_header("rumble")


def test_annotator_keep_and_clear():
    class Every2(Layer):
        name = "every2"

        def draw(self, ctx):
            return None if ctx.index % 2 else [draw.sphere((0, 0, 0), 1)]

    ann = Annotator(header(), [Every2(), CarInfo()])
    out = [ann(frame(t)) for t in range(4)]
    names = [[g["name"] for g in f["draw"]] for f in out]
    assert names == [["every2", "car_info"], ["car_info"], ["every2", "car_info"], ["car_info"]]
    label = out[0]["draw"][1]["prims"][0]
    assert label["text"].startswith("bot\nboost 33") and label["color"] == list(draw.ORANGE)


def test_acceleration_needs_previous_frame():
    ann = Annotator(header(), [Vectors("acc", cars=False)])
    first = ann(frame(0, vel=(0, 0, 0)))
    second = ann(frame(12, vel=(0, 0, 100)))  # 100 uu/s over 0.1 s -> 1000 uu/s^2 -> 100 uu arrow
    assert first.get("draw", [{"prims": []}])[0]["prims"] == []
    arrow = second["draw"][0]["prims"][0]
    assert arrow["b"] == pytest.approx([0, 0, 93 + 100], abs=1e-3)


def test_duplicate_layer_names():
    with pytest.raises(ValueError):
        Annotator(header(), [Vectors("vel"), Vectors("vel")])
