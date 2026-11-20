from rlviz.format import ReplayWriter, make_header
from rlviz.video import runs


def _frame(tick, draw=None):
    ball = {"pos": [0, 0, 93], "vel": [0, 0, 0], "ang_vel": [0, 0, 0], "rot": [1, 0, 0, 0, 1, 0, 0, 0, 1]}
    return {"tick": tick, "ball": ball, "cars": [], **({"draw": draw} if draw else {})}


def test_runs_split_at_gaps_and_skip_clearing_frame(tmp_path):
    path = tmp_path / "r.rlviz"
    with ReplayWriter(path, make_header("soccar")) as w:
        for t in range(100, 110):
            w.write(_frame(t, [{"name": "a", "prims": [{"t": "text2d", "pos": [0, 0], "text": "x"}]}] if t == 100 else None))
        w.write(_frame(110, [{"name": "a", "prims": []}]))
        for t in range(170, 180):
            w.write(_frame(t))
    rate, spans = runs(path)
    assert rate == 120 and spans == [(0, 9), (70, 79)]
