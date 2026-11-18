from rlviz import draw


def test_voxels_draw_only_outer_faces():
    m = draw.voxels((0, 0, 0), 10, [(0, 0, 0), (1, 0, 0)])
    assert len(m["tri"]) == 10 * 2          # 2 cells, 12 faces, 2 shared
    assert len(m["v"]) == 12
    assert all(0 <= i < len(m["v"]) for t in m["tri"] for i in t)


def test_surface_grid_triangles():
    grid = [[(x, y, 0) for y in range(3)] for x in range(4)]
    m = draw.surface(grid)
    assert len(m["v"]) == 12 and len(m["tri"]) == 3 * 2 * 2


def test_heightfield_colors_follow_value():
    m = draw.heightfield([0, 1], [0, 1], lambda x, y: 0.0, value=lambda x, y: x, color=(1, 1, 1, 0.5))
    assert len(m["colors"]) == 4
    assert m["colors"][0] == [0.2, 0.3, 1.0, 0.5]       # low end of the ramp
    assert m["colors"][-1] == [1.0, 0.25, 0.2, 0.5]     # high end


def test_optional_keys_only_when_set():
    assert "fill" not in draw.sphere((0, 0, 0), 1)
    assert draw.sphere((0, 0, 0), 1, fill=True)["fill"] is True
    b = draw.box((0, 0, 0), (1, 2, 3))
    assert "rot" not in b and "fill" not in b
