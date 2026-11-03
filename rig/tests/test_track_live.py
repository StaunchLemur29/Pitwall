from types import SimpleNamespace

from pitwall_rig.analysis import corner_mastery, width_advice
from pitwall_rig.models import Frame, GameStatus
from pitwall_rig.rig import Rig
from pitwall_rig.tracks.live import Drill, TrackState


def demo_model(demo):
    return demo.track_model(demo.session())


def test_demo_track_has_named_corners(demo):
    m = demo_model(demo)
    assert len(m.corners) >= 5
    assert any(c.name.startswith("Hairpin") for c in m.corners)
    assert all(0 <= c.entry <= c.apex <= c.exit <= 1 for c in m.corners)


def test_next_corner_wraps_round_the_lap(demo):
    m = demo_model(demo)
    first, last = m.corners[0], m.corners[-1]
    c, dist = m.next_corner(last.exit + 0.001)
    assert c.number == first.number and dist > 0
    c, dist = m.next_corner(first.apex)
    assert c.number == first.number and dist == 0


def frame_at(model, p, t, tyres_out=0):
    i = model.index_at(p)
    return Frame(t=t, status=GameStatus.LIVE, lap_progress=p, world=(model.line.x[i], 0.0, model.line.z[i]),
                 tyres_out=tyres_out)


def test_drill_attempts_streak_and_rewind(demo):
    m = demo_model(demo)
    st = TrackState(m)
    attempts = []
    st.on_attempt = attempts.append
    st.start_drill(Drill("Test", 0.20, 0.30, pass_within_s=0.5, pass_streak=2), best_ms=None)

    def run(seconds, start=0.15, end=0.35, t0=0.0, rewind_at=None, cut=False):
        steps = 200
        t = t0
        for k in range(steps + 1):
            p = start + (end - start) * k / steps
            if rewind_at is not None and p > rewind_at:
                p = rewind_at - 0.05  # Time Shift pulls the car back
                st.update(frame_at(m, p, t))
                return t
            t = t0 + seconds * k / steps
            st.update(frame_at(m, p, t, tyres_out=3 if cut and 0.25 < p < 0.26 else 0))
        return t

    t = run(20.0)  # 0.15→0.35 over 20 s: section (0.2→0.3) takes ~10 s
    assert len(attempts) == 1 and 9.5 < attempts[0]["time_ms"] / 1000 < 10.5
    st.update(frame_at(m, 0.5, t + 1))
    t = run(20.0, t0=t + 2, rewind_at=0.25)  # abandoned mid-section
    assert len(attempts) == 1
    st.update(frame_at(m, 0.5, t + 1))
    t = run(20.0, t0=t + 2, cut=True)  # cut the track: not clean, breaks the streak
    assert attempts[-1]["clean"] is False and st.drill.streak == 0
    for _ in range(2):
        st.update(frame_at(m, 0.5, t + 1))
        t = run(20.0, t0=t + 2)
    assert st.drill.streak == 2 and st.drill.passed


def test_width_advice_for_a_right_hander():
    c = SimpleNamespace(direction="R")
    good = {"entry_frac": 0.1, "apex_frac": 0.9, "exit_frac": 0.1, "coast_s": 0}
    assert width_advice(c, good, 200) == []
    lazy = {"entry_frac": 0.5, "apex_frac": 0.5, "exit_frac": 0.6, "coast_s": 0.8}
    tips = width_advice(c, lazy, 200)
    assert len(tips) == 4 and "left" in tips[0] and "right" in tips[1]
    # in a chicane the exit is the next entry: no exit advice
    assert len(width_advice(c, lazy, 30)) == 3


def test_mastery_grades():
    lap = lambda t: [{"corner": 1, "time_s": t}]  # noqa: E731
    steady = corner_mastery([lap(5.0), lap(5.02), lap(4.98), lap(5.01)])
    assert steady[1]["grade"] == "green"
    messy = corner_mastery([lap(5.0), lap(5.6), lap(4.9), lap(5.9)])
    assert messy[1]["grade"] == "red"
    assert corner_mastery([lap(5.0)])[1]["grade"] == "new"


def test_rig_loads_track_and_runs_a_drill(demo, clock, config, store):
    events = []
    rig = Rig(demo, store, config, emit=events.append, clock=clock)
    for _ in range(60 * 5):
        clock.advance(1 / 60)
        rig.tick()
    assert rig.track is not None
    assert any(e["type"] == "track" and e["track"] for e in events)
    live = rig.live()["track"]
    assert live and "corner" in live and live["frac"] is not None
    assert rig.drill_corner(1)
    clock.advance(1 / 60)
    rig.tick()
    assert rig.live()["track"]["drill"]["name"]


def test_pack_chapters_resolve_from_section_names():
    from pitwall_rig.packs import find_pack, resolve_chapters
    from pitwall_rig.tracks.ac_files import Section

    pack = find_pack("ks_nordschleife")
    assert pack is not None
    names = [c["from"] for c in pack["chapters"]]
    # pretend the layout has every start section, evenly spaced, plus one unknown
    secs = [Section(n, i / len(names), i / len(names) + 0.01) for i, n in enumerate(names)]
    secs.append(Section("Somewhere else", 0.5, 0.51))
    ch = resolve_chapters(pack, secs)
    assert [c.name for c in ch] == [c["name"] for c in pack["chapters"]]
    assert all(a.end == b.start for a, b in zip(ch, ch[1:]))
    assert ch[-1].end == 0.99999  # first chapter starts at the line
    assert find_pack("spa") is None


def test_yaw_calibrator_learns_the_mapping():
    import math

    from pitwall_rig.tracks.live import YawCalibrator

    cal = YawCalibrator()
    # Pretend the game's yaw is "0 = +z, clockwise positive": travel = 90 - yaw
    for k in range(200):
        travel = (k * 7) % 360 - 180
        yaw = math.radians(90 - travel)
        cal.observe(yaw, travel)
    assert cal.best == (-1, 90.0)
    assert abs(cal.heading(math.radians(90 - 30)) - 30) < 1e-6


def test_practice_sections_group_corner_families():
    from pitwall_rig.tracks.model import Corner, practice_sections

    def c(n, name, entry, exit_):
        return Corner(n, name, "R", 3, entry, (entry + exit_) / 2, exit_, 50.0)

    L = 7000.0
    corners = [
        c(1, "La Source", 0.05, 0.06),
        c(2, "Les Combes 1", 0.34, 0.35),
        c(3, "Les Combes 2", 0.36, 0.37),  # 70 m gap and same family → joined
        c(4, "Les Combes 3", 0.40, 0.41),  # 210 m gap but same family → joined
        c(5, "", 0.60, 0.61),
    ]
    ps = practice_sections(corners, L)
    assert [p.name for p in ps] == ["La Source", "Les Combes", "Turn 5"]
    assert ps[1].corners == [2, 3, 4]
    assert ps[1].start < 0.34 and ps[1].end > 0.41
