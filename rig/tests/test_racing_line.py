import math

from pitwall_rig.adapters.demo import DemoAdapter
from pitwall_rig.analysis import line_vs_optimal, width_advice
from pitwall_rig.tracks.ac_files import TrackLine
from pitwall_rig.tracks.model import Corner, TrackModel, _signed_curvature, detect_corners
from pitwall_rig.tracks.racing_line import offsets_to_points, optimal_offsets


def _line(pts, left, right):
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.dist(pts[i - 1], pts[i]))
    n = len(pts)
    return TrackLine([p[0] for p in pts], [0.0] * n, [p[1] for p in pts], d, [left] * n, [right] * n)


def _curvature_sq(line, pts):
    shifted = TrackLine([p[0] for p in pts], line.y, [p[1] for p in pts], line.dist, line.side_left, line.side_right)
    return sum(k * k for k in _signed_curvature(shifted))


def test_constant_radius_hugs_the_inside():
    # A clockwise circle in AC's plane is all right-handers: inside = right.
    r, n = 100.0, 400
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    off = optimal_offsets(_line(pts, left=6.0, right=4.0), margin_m=1.0)
    assert all(abs(a - (-3.0)) < 0.05 for a in off)  # 1 m inside the right edge, all the way round


def test_straight_lines_a_gentle_chicane():
    # A long oval whose straights have a small S-bend, much narrower than the
    # track is wide: the optimal line goes straight through it.
    pts = []
    for k in range(200):  # top straight, with the wiggle
        x = -500 + 5 * k
        pts.append((x, 100 + (1.5 * math.sin((x + 100) / 200 * 2 * math.pi) if -100 <= x <= 100 else 0.0)))
    for k in range(63):  # right-hand end
        a = math.pi / 2 - math.pi * k / 63
        pts.append((500 + 100 * math.cos(a), 100 * math.sin(a)))
    for k in range(200):
        pts.append((500 - 5 * k, -100))
    for k in range(63):
        a = -math.pi / 2 - math.pi * k / 63
        pts.append((-500 + 100 * math.cos(a), 100 * math.sin(a)))
    line = _line(pts, left=5.0, right=5.0)
    opt = offsets_to_points(line, optimal_offsets(line))
    wiggle = [p for p in opt if -100 <= p[0] <= 100 and p[1] > 50]
    zs = [p[1] for p in wiggle]
    assert max(zs) - min(zs) < 0.6  # all but straight through the S (the AI line moves 3 m)


def test_demo_track_line_is_smoother_and_on_the_road():
    a = DemoAdapter()
    m = a.track_model(a.session())
    line = m.line
    off = optimal_offsets(line)
    assert len(off) == len(line)
    assert all(-line.side_right[i] <= o <= line.side_left[i] for i, o in enumerate(off))
    ai = list(zip(line.x, line.z, strict=True))
    assert _curvature_sq(line, offsets_to_points(line, off)) < 0.97 * _curvature_sq(line, ai)
    # Tight corners (hairpins to medium) are apexed on the inside.
    tight = [c for c in m.corners if c.grade <= 3]
    inside = [c for c in tight if (off[c.apex_index] < -1.0 if c.direction == "R" else off[c.apex_index] > 1.0)]
    assert len(inside) >= 0.7 * len(tight)


def test_geometry_carries_the_optimal_line():
    a = DemoAdapter()
    m = a.track_model(a.session())
    g = m.geometry()
    assert len(g["optimal"]) == len(g["center"]) > 0
    no_edges = TrackModel("x", m.length_m, m.line, m.corners, has_edges=False)
    assert no_edges.geometry()["optimal"] == [] and no_edges.optimal() is None


def _right_hander_model():
    r, n = 100.0, 400
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    line = _line(pts, left=6.0, right=4.0)
    corner = Corner(1, "", "R", 3, entry=0.2, apex=0.25, exit=0.3, apex_radius_m=100.0)
    return TrackModel("ring", line.length, line, [corner]), corner


def test_line_vs_optimal_is_towards_the_inside():
    m, c = _right_hander_model()
    m.optimal()
    opt = m.optimal_at(c.apex)  # ≈ -2.8: right of the AI line, near the inside edge
    # Positions in metres left of the AI line: at turn-in on the optimal line,
    # 2 m wide of it at the apex, 1 m inside it on exit.
    data = {"entry_off_m": opt, "apex_off_m": opt + 2.0, "exit_off_m": opt - 1.0}
    assert line_vs_optimal(c, data, m) == {"entry": 0.0, "apex": -2.0, "exit": 1.0}
    assert line_vs_optimal(c, {}, m) is None


def test_width_advice_uses_the_optimal_line():
    c = Corner(1, "", "R", 3, entry=0.2, apex=0.25, exit=0.3, apex_radius_m=50.0)
    data = {"entry_frac": 0.9, "apex_frac": 0.1, "exit_frac": 0.9, "line": {"entry": 2.5, "apex": -2.0, "exit": 0.4}}
    tips = width_advice(c, data, None)
    assert any("Turn in from further left" in t and "2.5 m" in t for t in tips)
    assert any("closer to the right at the apex" in t and "2.0 m" in t for t in tips)
    assert not any("Use more road" in t for t in tips)  # 0.4 m on exit: close enough
    # The rule-of-thumb fractions are ignored when there's an optimal line.
    data["line"] = {"entry": 0.0, "apex": 0.0, "exit": 0.0}
    assert width_advice(c, data, None) == []


def test_detects_corners_on_the_optimal_line_track():
    # Sanity: the helper track has corners (keeps the ring fixture honest).
    m, _ = _right_hander_model()
    assert detect_corners(m.line)


def test_rig_sends_the_map_again_once_the_line_is_ready(demo, clock, config, store):
    import threading

    from pitwall_rig.rig import Rig
    from pitwall_rig.tracks import model as model_mod

    model_mod._OPTIMAL.clear()  # as on a fresh start
    events = []
    rig = Rig(demo, store, config, emit=events.append, clock=clock)
    clock.advance(1 / 60)
    rig.tick()  # session starts: the map goes out straight away, without the line
    first = [e for e in events if e["type"] == "track"]
    assert first and first[0]["track"]["optimal"] == []
    for t in threading.enumerate():
        if t.name == "optimal-line":
            t.join(30)
    tracks = [e for e in events if e["type"] == "track"]
    assert len(tracks) == 2 and len(tracks[-1]["track"]["optimal"]) == len(tracks[-1]["track"]["center"])
    assert any(e["type"] == "corners" for e in events[events.index(tracks[-1]) :])
