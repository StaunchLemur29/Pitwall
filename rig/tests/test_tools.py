"""Hardware checks: force feedback clipping and the brake pedal."""

from pitwall_rig.tools import brake_stops, ffb_report, pedal_report


def lap(ffb, brake_shape):
    n = 600
    tr = {"t": [i * 0.05 for i in range(n)], "p": [i / n for i in range(n)], "speed": [150.0] * n,
          "ffb": [ffb(i) for i in range(n)], "brake": [0.0] * n}
    for start, peak, release in brake_shape:  # (sample, peak, release samples)
        for k in range(6):
            tr["brake"][start + k] = peak * (k + 1) / 6
        for k in range(10):
            tr["brake"][start + 6 + k] = peak
        for k in range(release):
            tr["brake"][start + 16 + k] = peak * (1 - (k + 1) / release)
    return tr


def test_clipping_is_measured_and_the_gain_advice_follows():
    clipping = [lap(lambda i: 1.0 if i % 10 == 0 else 0.5, []) for _ in range(3)]  # 10 % of the time
    r = ffb_report(clipping)
    assert r["clipping_pct"] == 10.0 and r["gain_change_pct"] < 0 and "lower" in r["advice"]
    calm = [lap(lambda i: 0.4, []) for _ in range(3)]
    assert ffb_report(calm)["gain_change_pct"] > 0  # headroom: raise it
    assert ffb_report([{"t": [0], "p": [0], "speed": [0], "ffb": [0.0]}]) is None  # no force feedback recorded


def test_brake_stops_and_pedal_advice():
    shape = [(50 + 60 * k, 0.7, 12) for k in range(8)]
    stops = brake_stops(lap(lambda i: 0.0, shape))
    assert len(stops) == 8 and all(abs(s["peak"] - 0.7) < 1e-9 for s in stops)
    r = pedal_report([lap(lambda i: 0.0, shape)])
    assert r["full_pct"] == 0 and any("rarely use full brake" in n for n in r["notes"])
    slammed = [lap(lambda i: 0.0, [(50 + 60 * k, 1.0, 1) for k in range(8)])]
    notes = pedal_report(slammed)["notes"]
    assert any("100 % brake on most stops" in n for n in notes) and any("suddenly" in n for n in notes)
    assert pedal_report([lap(lambda i: 0.0, shape[:3])]) is None  # too few stops to say


def test_rig_tools_from_the_demo(demo, clock, config, store):
    from pitwall_rig.rig import Rig

    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    while len([x for x in store.laps(limit=100) if x["valid"]]) < 3:
        clock.advance(1 / 60)
        rig.tick()
    t = rig.tools()
    assert t["ffb"] and t["ffb"]["laps"] >= 3 and t["ffb"]["advice"]
    assert t["pedals"] and t["pedals"]["stops"] >= 8 and t["pedals"]["notes"]
