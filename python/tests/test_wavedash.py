from rlviz.layers.wavedash import landings

ROT = [1, 0, 0, 0, 1, 0, 0, 0, 1]


def _frame(tick, z, on_ground, flipped, vx):
    car = {"id": 1, "pos": [0.0, 0.0, z], "vel": [vx, 0.0, 0.0], "ang_vel": [0.0] * 3, "rot": ROT,
           "on_ground": on_ground, "flipped": flipped, "controls": [1, 0, -1, 0, 0, 0, 0, 0]}
    return {"tick": tick, "ball": {"pos": [3000.0, 0.0, 93.0], "vel": [0.0] * 3, "ang_vel": [0.0] * 3, "rot": ROT},
            "cars": [car]}


def test_landings_wavedash_and_plain():
    header = {"tick_rate": 120.0, "cars": [{"id": 1, "team": 0}]}
    frames = [_frame(t, 100, False, t >= 5, 1000 if t < 5 else 1500) for t in range(12)]
    frames += [_frame(t, 17, True, False, 1500) for t in range(12, 20)]
    # second run (tick gap): a landing with no dodge
    frames += [_frame(t, 100, False, False, 800) for t in range(100, 110)]
    frames += [_frame(t, 17, True, False, 800) for t in range(110, 115)]
    found = landings(header, frames)
    assert [(f.tick, f.ticks(), f.dodge_dir) for f in found] == [(12, 7, "front"), (110, None, "")]
    assert found[0].speed_before == 1000 and found[0].speed_after == 1500


def test_landing_to_press_and_hop():
    header = {"tick_rate": 120.0, "cars": [{"id": 1, "team": 0}]}
    frames = [_frame(t, 100, False, False, 1000) for t in range(5)]
    frames += [_frame(t, 20, True, False, 1000) for t in range(5, 9)]
    frames += [_frame(t, 20 + 4 * (t - 8), False, False, 1000) for t in range(9, 14)]
    frames += [_frame(t, 17, True, False, 1000) for t in range(14, 16)]
    for f in frames[8:]:
        f["cars"][0]["controls"][5] = 1.0  # pressed at tick 8
    found = landings(header, frames)
    assert (found[0].tick, found[0].jump_ticks, found[0].apex, found[0].cycle) == (5, 3, 20.0, 9)
