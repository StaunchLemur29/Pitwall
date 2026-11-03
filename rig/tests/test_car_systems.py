from pitwall_rig import car_profile
from pitwall_rig.analysis import analyse_systems
from pitwall_rig.models import Frame, GameStatus
from pitwall_rig.rig import Rig


def synthetic_lap(model, n=2000, drs=None, batt=None, gas=1.0):
    ps = [i / n for i in range(n)]
    return {
        "t": [i / n * 60 for i in range(n)],
        "p": ps,
        "x": [model.line.x[model.index_at(p)] for p in ps],
        "z": [model.line.z[model.index_at(p)] for p in ps],
        "speed": [200.0] * n, "brake": [0.0] * n, "gas": [gas] * n, "steer": [0.0] * n, "gear": [5] * n,
        "drs": [drs(p) for p in ps] if drs else [0] * n,
        "batt": [batt(p) for p in ps] if batt else [0.0] * n,
    }


def test_drs_available_but_not_opened_is_noted(demo):
    m = demo.track_model(demo.session())
    profile = {**car_profile.EMPTY, "drs": True}
    # Available from 10% to 20% of the lap: opened on one lap, not on the other.
    used = analyse_systems(synthetic_lap(m, drs=lambda p: 2 if 0.1 <= p <= 0.2 else 0), m, profile)
    assert used["drs"]["missed"] == [] and used["drs"]["open_m"] > 0
    lazy = analyse_systems(synthetic_lap(m, drs=lambda p: 1 if 0.1 <= p <= 0.2 else 0), m, profile)
    (miss,) = lazy["drs"]["missed"]
    assert miss["metres"] > 150 and miss["near"].startswith("before ")
    assert lazy["notes"][0].startswith("DRS was available but not opened")
    # A car without DRS never gets DRS notes.
    assert analyse_systems(synthetic_lap(m, drs=lambda p: 1), m, car_profile.EMPTY)["drs"] is None


def test_battery_running_out_is_noted(demo):
    m = demo.track_model(demo.session())
    profile = {**car_profile.EMPTY, "battery": True}
    out = analyse_systems(synthetic_lap(m, batt=lambda p: 0.0 if 0.5 <= p <= 0.6 else 0.6), m, profile)
    (empty,) = out["battery"]["empty"]
    assert empty["metres"] > 80 and "ran out" in out["notes"][0]
    full = analyse_systems(synthetic_lap(m, batt=lambda p: 0.9), m, profile)
    assert full["battery"]["empty"] == [] and "energy left to deploy" in full["notes"][0]


def test_car_profile_is_learnt_and_kept(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    for _ in range(60 * 3):
        clock.advance(1 / 60)
        rig.tick()
    p = rig.car_profile
    assert p["drs"] and p["ers"] and p["battery"] and p["deploy_modes"] == 4 and p["engine_brake_maps"] == 5
    assert p["abs"] and p["tc"] and p["brake_bias"]  # seen in telemetry
    rig.csp_sync({"abs_modes": 12, "tc_modes": 8})  # the in-game app knows the exact levels
    assert rig.car_profile["abs_levels"] == 12
    assert "ABS (12)" in car_profile.summary(rig.car_profile)
    # Next time, it's known before the first lap.
    s = rig.session
    assert store.car_profile(s.game, s.car)["tc_levels"] == 8
    rep = rig.corner_report()
    assert "systems" in rep and "DRS" in rep["car_systems"]


def test_frames_carry_battery_and_drs(demo, clock):
    seen_open = seen_avail = False
    for _ in range(60 * 60):
        clock.advance(1 / 60)
        f = demo.poll()
        seen_open |= f.drs_open
        seen_avail |= f.drs_available
        assert f.battery is None or 0 <= f.battery <= 1
    assert seen_avail
    assert isinstance(Frame(t=0, status=GameStatus.LIVE).drs_open, bool)
