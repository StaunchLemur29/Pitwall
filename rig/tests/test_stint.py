from pitwall_rig.stint import stint_report


def lap(i, ms, valid=True):
    return {"id": i, "lap_time_ms": ms, "valid": valid, "rewound": False, "unfinished": False}


def wrong(label, kind, lost):
    return {"label": label, "kind": kind, "lost_s": lost, "text": f"{label} {kind}"}


def test_the_pit_report_says_what_kept_happening_and_what_the_stint_did_to_the_car():
    laps = [lap(1, 141000), lap(2, 140500), lap(3, 142000, valid=False)]
    reviews = {
        1: {"wrong": [wrong("Bus Stop", "gear", 0.3)]},
        2: {"wrong": [wrong("Bus Stop", "gear", 0.2), wrong("Pouhon", "slide", 0.0)]},
        3: {"wrong": [wrong("Turn 4", "off", None)]},
    }
    r = stint_report(laps, reviews, pb_ms=139000, start={"fuel_l": 50.0}, now={"fuel_l": 38.0, "tyre_wear_pct": 1.2},
                     focus=None, laps_driven=3.0)
    assert r["laps"] == 3 and r["clean_laps"] == 2 and r["best"] == "2:20.500" and not r["new_pb"]
    assert r["repeats"][0]["label"] == "Bus Stop" and r["repeats"][0]["laps"] == 2
    assert "Bus Stop" in r["next"]
    assert any("4.0 L a lap" in c and "about 10 laps" in c for c in r["car"])
    assert any("1.2% worn" in c for c in r["car"])
    assert r["worst"][0]["kind"] in ("off", "slide")


def test_no_laps_no_report():
    assert stint_report([], {}, None, None, None, None) is None
