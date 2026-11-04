"""The time to beat: a realistic stretch target, per corner and for the lap."""

from pitwall_rig.analysis import PAST_BEST_S, time_to_beat


def m(usual, best, spread, grade, laps=10):
    return {"median_s": usual, "best_s": best, "spread_s": spread, "grade": grade, "laps": laps}


def test_consistent_corners_ask_more_than_messy_ones():
    t = time_to_beat({1: m(5.40, 5.20, 0.05, "green"), 2: m(5.40, 5.20, 0.30, "red")})
    assert t[1]["target_s"] < t[2]["target_s"] < 5.40
    assert t[2]["why"].startswith("Be consistent first")
    assert t[1]["gain_s"] == round(5.40 - t[1]["target_s"], 2)


def test_never_slower_than_usual_and_never_far_past_your_best():
    t = time_to_beat({1: m(5.00, 5.00, 0.02, "green")}, {1: {"time_s": 4.20}})
    assert t[1]["target_s"] >= 5.00 - PAST_BEST_S - 1e-9
    assert t[1]["target_s"] < 5.00  # consistent and at your best: push towards the optimal run
    assert "towards the optimal run" in t[1]["why"]


def test_needs_three_laps():
    assert time_to_beat({1: m(5.0, 4.9, 0.1, "new", laps=2)}) == {}


def test_rig_gives_a_lap_time_to_beat_and_drill_targets(demo, clock, config, store):
    from pitwall_rig.rig import Rig

    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    while len([lap for lap in store.laps(limit=100) if lap["valid"]]) < 4:
        clock.advance(1 / 60)
        rig.tick()
    rep = rig.corner_report()
    tb = rep["time_to_beat"]
    assert tb and tb["lap_ms"] <= tb["usual_lap_ms"]
    best = store.best_lap(rig.session.game, rig.session.track_key, rig.session.car)["lap_time_ms"]
    assert tb["lap_ms"] >= best * 0.997 - 1  # a stretch, not a fantasy
    assert tb["corners"] and all(c["target_s"] <= c["usual_s"] for c in tb["corners"])
    assert rig.live()["time_to_beat_ms"] == tb["lap_ms"]  # on the side screen
    assert any(ps.get("to_beat_s") for ps in rep["practice"])
    assert any(c.get("to_beat_s") for c in rep["lap"])
    assert rig.drill_section(rep["practice"][0]["number"])
    assert rig.track.drill.target_ms == round(rep["practice"][0]["to_beat_s"] * 1000)
