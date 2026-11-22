import threading

from pitwall_rig.adapters.demo import A_ACCEL, A_LAT
from pitwall_rig.optimal_run import learn_grip, simulate
from pitwall_rig.rig import Rig


def drive(rig, clock, laps):
    for _ in range(60 * 60 * 8):
        clock.advance(1 / 60)
        rig.tick()
        if len(rig.store.valid_lap_ids("demo", "demo_circuit", "demo_gt3")) >= laps:
            return


def wait_for_background():
    for t in threading.enumerate():
        if t.name in ("optimal-line", "optimal-run"):
            t.join(30)


def test_optimal_run_from_your_laps(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock, laps=3)
    wait_for_background()
    ids = store.fastest_valid_lap_ids("demo", "demo_circuit", "demo_gt3")
    traces = [store.trace(i) for i in ids]

    # It learns the demo car's real limits from how it was driven.
    grip = learn_grip(traces)
    assert grip is not None
    assert abs(grip.lat(30) - A_LAT) / A_LAT < 0.15
    assert abs(grip.accel(30) - A_ACCEL) / A_ACCEL < 0.15
    assert learn_grip([]) is None  # no laps, no guess

    # Driving the optimal line at that grip: quicker than you, but not absurdly.
    tr = simulate(rig.track.model, grip)
    best = min(store.lap(i)["lap_time_ms"] for i in ids) / 1000
    assert 0.75 * best < tr["t"][-1] < best
    assert all(0 <= b <= 1 for b in tr["brake"]) and all(0 <= g <= 1 for g in tr["gas"])
    assert not any(b > 0 and g > 0 for b, g in zip(tr["brake"], tr["gas"], strict=True))

    # The analysis carries it: per corner, with notes, and for the charts.
    rep = rig.corner_report()
    assert rep["optimal"] and rep["optimal"]["lap_s"] < best
    row = rep["lap"][0]
    assert row["opt"]["min_speed_kmh"] > 0 and row["opt"]["time_s"] > 0
    assert isinstance(row["opt_notes"], list)
    out = rig.optimal_trace(None, None, None)
    assert out and len(out["trace"]["t"]) > 100 and out["lap_s"] == rep["optimal"]["lap_s"]


# -- against the real Spa lap from the rig ---------------------------------------


def _real_lap(tmp_path):
    from tests.test_rig_recordings import play

    rig, _ = play("ac_spa_one_lap.pwrec", tmp_path)
    lap = next(l for l in rig.store.laps("ac", "spa@2022", "rss_gtmx_mercer_extreme_v8") if l["valid"])
    return rig.store.trace(lap["id"])


def _own_line(tr, step=2.0):
    """The line the lap drove, a point every 2 m."""
    import math

    from pitwall_rig.analysis import LapView

    view = LapView(tr)
    xs, ys, zs, ps = [], [], [], []
    for i in view.idx:
        if not xs or math.hypot(tr["x"][i] - xs[-1], tr["z"][i] - zs[-1]) >= step:
            xs.append(tr["x"][i])
            ys.append(tr["y"][i])
            zs.append(tr["z"][i])
            ps.append(tr["p"][i])
    return xs, ys, zs, ps, view


def test_the_model_can_drive_your_real_line_as_fast_as_you_did(tmp_path):
    """The check on the physics: the car's grip learnt from a real lap, then that
    lap's own line driven with it. It should be about as quick as you were or
    quicker nearly everywhere: where it's much slower, the model is missing
    something the car really did. (Before the hills were modelled it was over
    60 km/h slow through Raidillon, and slower than the lap on 23 % of it.)"""
    from pitwall_rig.optimal_run import lap_time, simulate_path

    tr = _real_lap(tmp_path)
    grip = learn_grip([tr])
    xs, ys, zs, ps, view = _own_line(tr)
    sim = simulate_path(xs, zs, ps, grip, ys=ys)
    real = tr["t"][-1]
    assert 0.93 * real < lap_time(sim) < real  # a little quicker than you, not absurdly

    diffs = [(p, sim["speed"][j] - tr["speed"][view.at(p)]) for j, p in enumerate(sim["p"]) if 0.03 < p < 0.99]
    slower = sum(1 for _, d in diffs if d < -3) / len(diffs)
    assert slower < 0.12, slower
    # The bottom of Eau Rouge: over twice the car's weight on the tyres, taken at 260.
    dip = [d for p, d in diffs if 0.156 < p < 0.163]
    assert min(dip) > -15, min(dip)


def test_hills_change_how_fast_a_bend_can_be_taken():
    """A dip presses the car into the road (more grip), a crest unloads it."""
    from pitwall_rig.optimal_run import Grip, _corner_speed, hills, load_factor

    grip = Grip(lat0=15.0, lat_k=0.0, brake0=15.0, brake_k=0.0, accel_v=[10.0, 60.0], accel_a=[6.0, 2.0], top_speed=80.0)
    flat = _corner_speed(grip, 1 / 150, 0.0)
    assert abs(flat - (15.0 * 150) ** 0.5) < 0.2
    assert _corner_speed(grip, 1 / 150, 1 / 400) > flat * 1.2  # a dip
    assert _corner_speed(grip, 1 / 150, -1 / 400) < flat * 0.85  # a crest
    assert load_factor(60.0, -1.0) == 0.25  # never less than a quarter: the car's nearly flying
    # A parabola-shaped dip, 2 m between points: the curvature and slope come back out of the heights.
    ys = [((i - 100) * 2.0) ** 2 / (2 * 500.0) for i in range(201)]
    kv, slope = hills(ys, [2.0] * 201, closed=False)
    assert abs(kv[100] - 1 / 500) < 1e-4 and abs(slope[100]) < 1e-6 and slope[150] > 0.15


def test_engine_power_isnt_cut_by_cornering_when_the_tyres_have_plenty():
    """Flat out through a fast sweeper: the engine, not the tyres, limits how
    fast the car gains speed, so cornering takes nothing from it."""
    import math

    from pitwall_rig.optimal_run import Grip, simulate_path

    grip = Grip(lat0=20.0, lat_k=0.0, brake0=20.0, brake_k=0.0, accel_v=[10.0, 70.0], accel_a=[8.0, 1.0],
                top_speed=90.0, traction0=8.0)
    # An oval: 500 m straights, 300 m radius ends (taken at up to 77 m/s on 20 m/s² of grip).
    xs, zs = [], []
    for i in range(250):
        xs.append(-300.0), zs.append(i * 2.0)
    for i in range(471):
        a = math.pi - i * math.pi / 471
        xs.append(300 * math.cos(a)), zs.append(500 + 300 * math.sin(a))
    for i in range(250):
        xs.append(300.0), zs.append(500 - i * 2.0)
    for i in range(471):
        a = -i * math.pi / 471
        xs.append(300 * math.cos(a)), zs.append(300 * math.sin(a))
    n = len(xs)
    sim = simulate_path(xs, zs, [i / n for i in range(n)], grip)
    assert min(sim["speed"]) / 3.6 > 55  # never falls far below the bend's limit...
    i = 250 + 235  # ...and half-way round a bend it's still gaining speed or at the limit
    assert sim["speed"][i + 20] >= sim["speed"][i] - 0.2
