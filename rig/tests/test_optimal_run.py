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
