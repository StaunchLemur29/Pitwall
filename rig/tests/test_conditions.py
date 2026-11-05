"""The coach tells you what changed: a crash, dirty or worn tyres, the track, rain, dusk."""

from dataclasses import replace

from pitwall_rig.conditions import Conditions
from pitwall_rig.models import Frame, GameStatus

BASE = Frame(t=0.0, status=GameStatus.LIVE, speed_kmh=200.0, fuel_l=50.0, tyre_wear=[100.0] * 4,
             tyre_dirt=[0.0] * 4, damage=[0.0] * 5, air_c=20.0, road_c=28.0, grip=0.96)


def run(c, frames):
    for i, f in enumerate(frames):
        c.update(f, float(i))
    return c.current_notice(float(len(frames)))


def test_contact_says_where_the_car_is_damaged():
    c = Conditions()
    n = run(c, [BASE, replace(BASE, damage=[2.0, 0, 0, 0, 0])])
    assert n["kind"] == "crash" and "front" in n["text"]


def test_dirty_tyres_after_going_off_then_clean_again():
    c = Conditions()
    assert run(c, [BASE, replace(BASE, tyre_dirt=[0, 1.2, 0, 0])])["kind"] == "dirt"
    assert run(c, [replace(BASE, tyre_dirt=[0, 0.05, 0, 0])])["kind"] == "clean"


def test_a_hard_stop_on_track_warns_about_tyres():
    c = Conditions()
    n = run(c, [BASE, replace(BASE, speed_kmh=10.0)])
    assert n["kind"] == "crash" and "tyres" in n["text"]


def test_track_temperature_grip_and_wear_changes():
    c = Conditions()
    assert run(c, [BASE, replace(BASE, road_c=33.0)])["kind"] == "track"
    assert "grip up" in run(c, [replace(BASE, road_c=33.0, grip=0.99)])["text"].lower()
    assert run(c, [replace(BASE, road_c=33.0, grip=0.99, tyre_wear=[96.5] * 4)])["kind"] == "wear"


def test_rain_and_dusk_from_the_in_game_app():
    c = Conditions()
    c.set_env({"time_h": 19, "time_m": 0, "rain": 0.0})
    run(c, [BASE, BASE])
    c.set_env({"time_h": 19, "time_m": 45, "rain": 0.0})
    assert run(c, [BASE])["kind"] == "light"
    c.set_env({"time_h": 19, "time_m": 50, "rain": 0.3})
    assert run(c, [BASE])["kind"] == "weather"


def test_the_lap_keeps_its_conditions():
    c = Conditions()
    c.set_env({"time_h": 14, "time_m": 5})
    run(c, [BASE, replace(BASE, tyre_wear=[98.0] * 4)])
    snap = c.snapshot(replace(BASE, tyre_wear=[98.0] * 4))
    assert snap["road_c"] == 28.0 and snap["grip"] == 0.96 and snap["tyre_wear_pct"] == 2.0 and snap["time"] == "14:05"


def test_notices_fade():
    c = Conditions()
    run(c, [BASE, replace(BASE, damage=[2.0, 0, 0, 0, 0])])
    assert c.current_notice(100.0) is None
