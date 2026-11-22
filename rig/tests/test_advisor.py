"""The electronics and tyre-pressure advisor (advisor.py)."""

from pitwall_rig.advisor import Advisor, advise, ideal_pressures
from pitwall_rig.models import Frame, GameStatus
from pitwall_rig.rig import Rig

from .test_optimal_run import drive, wait_for_background

R = 0.33  # the test car's wheel radius


def frames(adv, seconds, v_kmh, *, brake=0.0, gas=0.3, wheels=(1, 1, 1, 1), t0=0.0, p0=0.0, abs_=0.0, tc=0.0, psi=None):
    """Feed ``seconds`` of steady driving at 60 Hz; each wheel turning at ``wheels`` x road speed."""
    n = int(seconds * 60)
    v = v_kmh / 3.6
    for i in range(n):
        adv.feed(Frame(
            t=t0 + i / 60, status=GameStatus.LIVE, packet_id=int(t0 * 60) + i + 1, speed_kmh=v_kmh, brake=brake, gas=gas,
            lap_progress=p0 + i * 1e-5, wheel_speed=[v / R * w for w in wheels], abs=abs_, tc=tc,
            tyre_pressure_psi=psi or [27.0, 27.0, 26.5, 26.5],
        ))
    return t0 + seconds


def test_it_learns_the_wheels_then_spots_lockups_and_wheelspin():
    adv = Advisor()
    assert adv.slip(Frame(t=0, speed_kmh=150, wheel_speed=[100] * 4)) is None  # doesn't know the wheels yet
    t = frames(adv, 2, 150)  # rolling freely: learns what a turn of each wheel covers
    assert abs(adv._radius[0] - R) < 0.005
    t = frames(adv, 0.5, 140, brake=0.9, gas=0, wheels=(0.4, 1, 1, 1), t0=t, p0=0.30)  # front left locks
    t = frames(adv, 0.5, 100, t0=t, p0=0.31)
    t = frames(adv, 0.05, 140, brake=0.9, gas=0, wheels=(0.4, 1, 1, 1), t0=t, p0=0.40)  # a blip: too short to count
    t = frames(adv, 0.5, 100, t0=t, p0=0.41)
    t = frames(adv, 0.5, 120, brake=0.8, gas=0, wheels=(1, 1, 0.5, 0.6), t0=t, p0=0.50)  # the rears lock
    t = frames(adv, 0.5, 90, gas=1.0, wheels=(1, 1, 1.4, 1.4), t0=t, p0=0.60)  # wheelspin
    t = frames(adv, 0.5, 100, t0=t, p0=0.61)
    t = frames(adv, 0.5, 40, brake=0.9, gas=0, wheels=(0, 0, 1, 1), t0=t, p0=0.70)  # too slow to matter
    frames(adv, 4, 150, t0=t, p0=0.71)
    lap = adv.end_lap({"bb": 0.62})
    kinds = [(e["kind"], round(e["p"], 2)) for e in lap["events"]]
    assert kinds == [("lock_front", 0.30), ("lock_rear", 0.50), ("spin", 0.60)]
    assert lap["psi"] == [27.0, 27.0, 26.5, 26.5] and lap["settings"] == {"bb": 0.62}
    assert adv.end_lap() == {"events": [], "psi": None, "abs_share": None, "tc_share": None, "settings": {}}  # a fresh lap


def test_no_wheel_speeds_no_findings():
    adv = Advisor()
    for i in range(300):
        adv.feed(Frame(t=i / 60, status=GameStatus.LIVE, packet_id=i + 1, speed_kmh=150, gas=0.3))
    assert adv.end_lap() is None  # old recordings, games that don't report them


def lap(events=(), psi=None, settings=None, abs_share=None, tc_share=None):
    return {"events": [{"kind": k, "p": p, "s": 0.3, "worst": 0.5} for k, p in events], "psi": psi,
            "abs_share": abs_share, "tc_share": tc_share, "settings": settings or {"bb": 0.62}}


def corner_at(p):
    return (5, "Turn 5") if p < 0.5 else (9, "Turn 9")


def test_front_lockups_at_the_same_corner_call_for_bias_to_the_rear():
    laps = [lap([("lock_front", 0.3)]), lap(), lap([("lock_front", 0.31)]), lap()]
    out = advise(laps, {"brake_bias": True}, corner_at)
    a = out["advice"][0]
    assert a["key"] == "lock_front" and a["do"] == "Move the brake bias 1 % to the rear."
    assert "2 of your last 4 laps" in a["why"] and "Turn 5" in a["why"]
    assert a["corner"] == 5  # where a live tip about it shows


def test_rear_lockups_call_for_the_opposite():
    laps = [lap([("lock_rear", 0.7)]), lap([("lock_rear", 0.71), ("lock_front", 0.2)]), lap([("lock_rear", 0.7)])]
    a = advise(laps, {"brake_bias": True}, corner_at)["advice"][0]
    assert a["key"] == "lock_rear" and "to the front" in a["do"] and a["corner"] == 9


def test_with_abs_on_it_suggests_more_abs_and_with_tc_more_tc():
    s = {"bb": 0.6, "abs": 2, "tc": 3}
    laps = [lap([("lock_front", 0.3), ("spin", 0.8)], settings=s) for _ in range(3)]
    keys = {a["key"]: a["do"] for a in advise(laps, {"brake_bias": True, "abs": True, "tc": True}, corner_at)["advice"]}
    assert keys["lock_front"].startswith("Try one step more ABS.")
    assert keys["wheelspin"] == "Try one step more TC."
    # ...and with them switched off (mode 0), to turn them on
    off = {"bb": 0.6, "abs": 0, "tc": 0}
    laps = [lap([("lock_front", 0.3), ("spin", 0.8)], settings=off) for _ in range(3)]
    keys = {a["key"]: a["do"] for a in advise(laps, {"brake_bias": True, "abs": True, "tc": True}, corner_at)["advice"]}
    assert keys["lock_front"].startswith("Turn the ABS on") and keys["wheelspin"].startswith("Turn the TC on")


def test_a_one_off_says_nothing_and_changing_a_setting_starts_again():
    assert advise([lap([("lock_front", 0.3)]), lap(), lap(), lap()], {"brake_bias": True}, corner_at)["advice"] == []
    assert advise([lap([("lock_front", 0.3)]), lap([("lock_front", 0.3)])], {}, corner_at)["advice"] == []  # too few laps
    # You moved the bias after three laps of lock-ups: one lap on the new setting isn't evidence yet.
    old = [lap([("lock_front", 0.3)], settings={"bb": 0.62}) for _ in range(3)]
    out = advise([lap(settings={"bb": 0.61}), *old], {"brake_bias": True}, corner_at)
    assert out["laps"] == 1 and out["advice"] == []


def test_busy_aids():
    s = {"abs": 2, "tc": 2}
    laps = [lap(settings=s, abs_share=0.7, tc_share=0.5) for _ in range(3)]
    keys = [a["key"] for a in advise(laps, {"abs": True, "tc": True}, corner_at)["advice"]]
    assert keys == ["tc_busy", "abs_busy"]
    assert advise([lap(settings=s, abs_share=0.2, tc_share=0.1) for _ in range(3)], {"abs": True, "tc": True}, corner_at)["advice"] == []


def test_tyre_pressures():
    laps = [lap(psi=[28.6, 27.0, 26.5, 26.6]) for _ in range(3)]
    out = advise(laps, {}, corner_at)
    (a,) = out["advice"]
    assert a["key"] == "psi_front" and a["do"] == "Start the front left 1.6 psi lower than the front right."
    assert out["psi"] == [28.6, 27.0, 26.5, 26.6]
    # With the car's ideal known: each wheel against it.
    out = advise(laps, {}, corner_at, target_psi=(27.0, 26.5))
    (a,) = out["advice"]
    assert a["do"] == "Front left: lower the cold pressure by 1.6 psi."
    assert advise([lap(psi=[27.2, 27.0, 26.5, 26.6])] * 3, {}, corner_at, target_psi=(27.0, 26.5))["advice"] == []


def test_ideal_pressures_from_the_cars_files(tmp_path):
    d = tmp_path / "content" / "cars" / "some_mod" / "data"
    d.mkdir(parents=True)
    (d / "tyres.ini").write_text("[HEADER]\nVERSION=10\n\n[FRONT]\nNAME=Slick\nPRESSURE_IDEAL=27 ; psi\n\n[REAR]\nPRESSURE_IDEAL=26.5\n")
    assert ideal_pressures(str(tmp_path), "some_mod") == (27.0, 26.5)
    assert ideal_pressures(str(tmp_path), "packed_car") is None  # only a data.acd: can't be read
    assert ideal_pressures(None, "some_mod") is None


def test_on_the_demo_the_rig_gives_advice_and_puts_it_in_the_pit_report(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    drive(rig, clock, laps=5)
    wait_for_background()
    out = rig.advice()
    assert out["laps"] >= 3 and out["psi"] is not None
    keys = [a["key"] for a in out["advice"]]
    assert "psi_front" in keys  # the demo car's front left runs hot
    assert all(a["do"] and a["why"] for a in out["advice"])
