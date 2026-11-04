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


def test_coach_strip_focus_last_lap_and_cold_tyres(demo, clock, config, store):
    from pitwall_rig.models import Frame, GameStatus
    from pitwall_rig.rig import Rig

    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    while len([lap for lap in store.laps(limit=100) if lap["valid"]]) < 4:
        clock.advance(1 / 60)
        rig.tick()
    coach = rig.live()["coach"]
    f = coach["focus"]
    tb = rig.corner_report()["time_to_beat"]
    biggest = max(tb["corners"], key=lambda c: c["gain_s"])
    assert f and f["corner"] == biggest["corner"] and f["to_beat_s"] == biggest["target_s"]
    assert coach["last_lap"] and "wrong" in coach["last_lap"]  # just finished a lap
    # Focus stays put for the session until it's met twice.
    rig._focus["beaten"] = 2
    rig._coach_after_lap(store.laps(limit=1)[0]["id"], rig.corner_report(), tb)
    assert rig._focus is None or rig._focus["corner"] != f["corner"]
    # Cold tyres: after a teleport/reset they drop; warm again near the usual temperature.
    rig.car_profile["tyre_working_c"] = 85.0
    cold = Frame(t=clock(), status=GameStatus.LIVE, speed_kmh=0, tyre_core_temp_c=[40.0] * 4)
    rig.frame = cold
    rig._note_tyres(cold)
    assert rig.live()["coach"]["tyres"]["cold"]
    warm = Frame(t=clock(), status=GameStatus.LIVE, speed_kmh=150, tyre_core_temp_c=[82.0] * 4)
    rig.frame = warm
    rig._note_tyres(warm)
    assert rig.live()["coach"]["tyres"] is None
