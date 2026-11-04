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


def test_drill_counts_every_run_and_never_resets(demo):
    m = demo_model(demo)
    st = TrackState(m)
    attempts = []
    st.on_attempt = attempts.append
    st.start_drill(Drill("Test", 0.20, 0.30), best_ms=None)

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
    t = run(20.0, t0=t + 2, cut=True)  # cut the track: not clean, and not a best, but it still counts
    assert attempts[-1]["clean"] is False and attempts[-1]["new_best"] is False
    st.update(frame_at(m, 0.5, t + 1))
    t = run(24.0, t0=t + 2)  # a slow run: counted, nothing resets
    st.update(frame_at(m, 0.5, t + 1))
    t = run(18.0, t0=t + 2)  # a quicker one: new best
    assert st.drill.attempts == 4
    assert attempts[-1]["new_best"] is True and st.drill.best_ms == attempts[-1]["time_ms"]
    assert [a["new_best"] for a in attempts] == [True, False, False, True]


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


def test_retry_run_up_follows_the_reference_lap(demo):
    m = demo_model(demo)
    ts = TrackState(m)
    d = Drill(name="x", start_p=0.5, end_p=0.6)
    assert ts.lead_in_m(d, 4) == 160  # no reference yet: a typical speed
    # Reference lap at a steady 50 m/s: 4 s of driving is 200 m.
    n = 2000
    lap_s = m.length_m / 50
    trace = {k: [0.0] * n for k in ("speed", "brake", "gas", "steer", "gear")}
    trace["p"] = [i / n for i in range(n)]
    trace["t"] = [i / n * lap_s for i in range(n)]
    trace["x"] = [m.line.x[m.index_at(q)] for q in trace["p"]]
    trace["z"] = [m.line.z[m.index_at(q)] for q in trace["p"]]
    ts.set_reference(trace)
    assert abs(ts.lead_in_m(d, 4) - 200) < 3


def test_compare_notes_name_the_biggest_differences():
    from pitwall_rig.analysis import compare_notes

    mine = {"min_speed_kmh": 92.0, "exit_kmh": 140.0, "brake_m": 120, "throttle_m": 40, "coast_s": 0.6, "apex_gear": 2}
    best = {"min_speed_kmh": 101.0, "exit_kmh": 142.0, "brake_m": 100, "throttle_m": 15, "coast_s": 0.1, "apex_gear": 3}
    notes = compare_notes(mine, best, "your best lap")
    assert notes[0] == "9 km/h slower at the slowest point than your best lap."
    assert "Braked 20 m earlier than your best lap." in notes
    assert "Back to full throttle 25 m later than your best lap." in notes
    assert any(n.startswith("Coasted 0.5 s longer") for n in notes)
    assert not any("exit" in n for n in notes)  # 2 km/h is within the noise
    assert compare_notes(mine, mine, "x") == []


def test_corner_report_compares_with_the_best_lap(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    for _ in range(60 * 60 * 4):
        clock.advance(1 / 60)
        rig.tick()
        if len(store.valid_lap_ids("demo", rig.session.track_key, rig.session.car)) >= 3:
            break
    rep = rig.corner_report()
    assert rep["compare_lap_id"] is not None and rep["compare_lap_id"] != rep["lap_id"]
    assert rep["compare_label"]
    row = rep["lap"][0]
    assert "vs_s" in row and isinstance(row["notes"], list)
    assert {"brake_m", "entry_kmh", "exit_kmh", "throttle_m", "peak_brake"} <= row.keys()
    # Looking at the best lap itself compares with the next best.
    best = rig.reference.lap_id
    rep = rig.corner_report(best)
    assert rep["compare_lap_id"] not in (None, best)


def test_braking_point_moves_with_approach_speed(demo):
    m = demo_model(demo)
    ts = TrackState(m)
    # Reference: 200 km/h everywhere on the approach, braking 100 m before the
    # slowest point (100 km/h).
    n = 4000
    trace = {"p": [i / n for i in range(n)], "t": [i / n * 60 for i in range(n)], "speed": [200.0] * n}
    ts.ref_view = __import__("pitwall_rig.analysis", fromlist=["LapView"]).LapView(trace)
    L = m.length_m
    ref = {"brake_p": 0.5, "min_speed_p": 0.5 + 100 / L, "entry_kmh": 200.0, "min_speed_kmh": 100.0}

    def settle(speed):
        ts._shift_corner = None
        for _ in range(60):
            s = ts._speed_shift(1, ref, 0.45, speed)
        return s

    assert abs(settle(200)) < 0.5  # same speed: same braking point
    faster = settle(210)  # 10 km/h quicker: brake earlier
    slower = settle(185)
    assert 10 < faster < 20  # (210²-100²)/(200²-100²) × 100 m ≈ 114 m
    assert -30 < slower < -15
    assert abs(settle(300) - 50) < 0.01  # capped at half the braking distance


def test_analysis_works_for_a_past_car_and_track(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    for _ in range(60 * 60 * 4):
        clock.advance(1 / 60)
        rig.tick()
        if len(store.valid_lap_ids("demo", rig.session.track_key, rig.session.car)) >= 2:
            break
    s = rig.session
    # A fresh start with no game session: pick the car + track from the list.
    later = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    combos = later.combos()
    assert [(c["car"], c["track_key"]) for c in combos] == [(s.car, s.track_key)]
    assert combos[0]["valid_laps"] >= 2 and combos[0]["live"] is False
    rep = later.corner_report(game=s.game, car=s.car, track_key=s.track_key)
    assert rep["lap"] and rep["live"] is False and rep["track_key"] == s.track_key
    assert rep["compare_lap_id"] is not None
    assert later.track_geometry(s.game, s.car, s.track_key)["corners"]
    # Asking by lap id alone finds its car + track too.
    assert later.corner_report(rep["lap_id"])["lap"] == rep["lap"]


def test_brake_cue_holds_at_the_braking_point(demo):
    m = demo_model(demo)
    ts = TrackState(m)
    L = m.length_m
    c = next(k for k in m.corners if (k.apex - k.entry) * L > 30)
    bp = c.entry - 60 / L  # brake 60 m before the corner
    ts.ref_corners = {c.number: {"brake_p": bp}}

    def brake_at(metres_after_brake_point):
        p = (bp + metres_after_brake_point / L) % 1.0
        out = ts.update(frame_at(m, p, 0.0))
        return out["corner"]["brake_in_m"] if out["corner"]["number"] == c.number else "other corner"

    assert brake_at(-100) == 100  # counting down
    assert brake_at(-1) == 1
    assert brake_at(10) == -10  # just past: "brake now", not gone
    assert brake_at(35) == -35
    assert brake_at(50) is None  # well past it: cleared


def test_teleporting_through_a_drill_section_records_nothing(demo):
    m = demo_model(demo)
    st = TrackState(m)
    attempts = []
    st.on_attempt = attempts.append
    st.start_drill(Drill("Test", 0.20, 0.30), best_ms=None)
    packet = 0

    def at(p, t):
        nonlocal packet
        packet += 1
        i = m.index_at(p)
        f = Frame(t=t, status=GameStatus.LIVE, packet_id=packet, lap_progress=p, lap_time_ms=int(t * 1000),
                  speed_kmh=150, world=(m.line.x[i], 0.0, m.line.z[i]))
        st.update(f)

    t = 0.0
    p = 0.17
    while p < 0.25:  # drive into the section...
        at(p, t)
        p, t = p + 0.0005, t + 0.05
    at(0.32, t + 0.05)  # ...and teleport out past its end
    assert attempts == []
    at(0.10, t + 0.1)  # teleport before the start (e.g. the run-up) and land inside the section
    at(0.25, t + 0.15)
    p, t = 0.25, t + 0.15
    while p < 0.32:
        p, t = p + 0.0005, t + 0.05
        at(p, t)
    assert attempts == []  # never crossed the start line driving


def test_teleport_point_lets_you_reach_reference_speed_from_a_standstill(demo):
    m = demo_model(demo)
    ts = TrackState(m)
    d = Drill(name="x", start_p=0.5, end_p=0.6)
    # No reference: a typical speed (40 m/s) at the fallback acceleration, with the margin.
    want = 40**2 / (2 * ts.FALLBACK_ACCEL * ts.STANDING_MARGIN)
    assert abs(ts.standing_start_m(d) - want) < 5
    assert ts.standing_start_m(d, min_m=500) == 500  # never closer than asked
    # Reference lap: flat out at 8 m/s² up to 50 m/s, then steady.
    n = 4000
    trace = {k: [0.0] * n for k in ("brake", "steer", "gear", "speed", "t")}
    trace["gas"] = [1.0] * n
    trace["p"] = [i / n for i in range(n)]
    t = speed = 0.0
    for i in range(n):
        trace["t"][i], trace["speed"][i] = t, speed * 3.6
        ds = m.length_m / n
        dt = ds / max(speed, 1.0)
        t, speed = t + dt, min(50.0, speed + 8.0 * dt)
    trace["x"] = [m.line.x[m.index_at(q)] for q in trace["p"]]
    trace["z"] = [m.line.z[m.index_at(q)] for q in trace["p"]]
    ts.set_reference(trace)
    acc = ts.accel_by_speed()
    assert acc and all(abs(a - 8.0) < 0.5 for _, a in acc)
    want = 50**2 / (2 * 8.0 * ts.STANDING_MARGIN)  # ~184 m
    assert abs(ts.standing_start_m(d) - want) < 10
