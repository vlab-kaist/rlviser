import math

import pytest

flat = pytest.importorskip("rlbot.flat")

from rlviz import draw  # noqa: E402
from rlviz.layers import DEFAULT_LAYERS, Annotator, make_layers  # noqa: E402
from rlviz.rlbot import group_id, packet_frame, packet_header, render_messages, rot_rows  # noqa: E402


def _packet():
    car = flat.PlayerInfo(
        physics=flat.Physics(flat.Vector3(100, -200, 17), flat.Rotator(0.0, math.pi / 2, 0.0),
                             flat.Vector3(0, 1000, 0), flat.Vector3(0, 0, 1)),
        hitbox=flat.BoxShape(118, 84.2, 36.2), air_state=flat.AirState.OnGround, name="bot", team=1, boost=48)
    ball = flat.BallInfo(physics=flat.Physics(flat.Vector3(0, 0, 500), flat.Rotator(),
                                              flat.Vector3(300, 0, 200), flat.Vector3()))
    return flat.GamePacket(players=[car], balls=[ball], boost_pads=[flat.BoostPadState(True)],
                           match_info=flat.MatchInfo(frame_num=1234))


def test_rot_rows_yaw():
    rows = rot_rows(flat.Rotator(0.0, math.pi / 2, 0.0))
    assert rows[0:3] == pytest.approx([0, 1, 0], abs=1e-9)   # forward along +y
    assert rows[6:9] == pytest.approx([0, 0, 1], abs=1e-9)   # up


def test_packet_frame_runs_layers():
    packet = _packet()
    field = flat.FieldInfo(boost_pads=[flat.BoostPad(flat.Vector3(0, 0, 70), True)])
    header = packet_header(packet, field, flat.MatchConfiguration())
    assert header["cars"][0]["team"] == 1 and header["pads"][0]["big"]
    frame = packet_frame(packet)
    assert frame["tick"] == 1234 and frame["cars"][0]["on_ground"] and frame["pads"] == [True]
    names = [n for n in DEFAULT_LAYERS if n != "ball_prediction"]  # that one needs RocketSim's meshes
    out = Annotator(header, make_layers(names))(frame)
    drawn = {g["name"] for g in out["draw"] if render_messages(g["prims"])}
    assert {"car_info", "vectors.vel"} <= drawn  # acceleration needs a previous frame


def test_render_messages_shapes():
    prims = [
        draw.line((0, 0, 0), (1, 0, 0)),
        draw.polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0)]),
        draw.arrow((0, 0, 0), (100, 0, 0)),
        draw.sphere((0, 0, 0), 50, fill=True),
        draw.box((0, 0, 0), (10, 20, 30)),
        draw.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [(0, 1, 2), (1, 3, 2)]),
        draw.text((0, 0, 0), "hi"),
        draw.text2d(0.1, 0.1, "hi"),
        {"t": "cone"},
    ]
    kinds = [type(m.variety).__name__ for m in render_messages(prims)]
    assert kinds.count("Line3D") == 1 + 3 + 4 + 4  # line, arrow, box pillars, mesh outline
    assert kinds.count("PolyLine3D") == 1 + 3 + 2  # polyline, sphere circles, box top/bottom
    assert kinds.count("String3D") == 1 and kinds.count("String2D") == 1


def test_group_id_stable():
    assert group_id("car_info") == group_id("car_info") != group_id("vectors.vel")
