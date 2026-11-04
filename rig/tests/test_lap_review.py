"""The good and the bad of a lap against your usual."""

from types import SimpleNamespace

from pitwall_rig.analysis import lap_review, off_track_runs, typical_corners


def corner(num, t, vmin=100.0, exit_kmh=150.0, brake_m=100, throttle_m=20, coast=0.0, gear=3):
    return {"corner": num, "time_s": t, "min_speed_kmh": vmin, "exit_kmh": exit_kmh, "entry_kmh": 220.0,
            "brake_m": brake_m, "throttle_m": throttle_m, "coast_s": coast, "apex_gear": gear}


C = [SimpleNamespace(number=n, label=f"Turn {n}", entry=e, apex=e + 0.02, exit=e + 0.04)
     for n, e in ((1, 0.10), (2, 0.40), (3, 0.70))]


class Model:
    corners = C
    length_m = 4000.0

    def next_corner(self, p):
        for c in C:
            if c.entry > p:
                return c, (c.entry - p) * self.length_m
        return C[0], (1 + C[0].entry - p) * self.length_m


def usual(n=6):
    # Steady laps: Turn 1 in 5.00 s, Turn 2 in 6.00 s, Turn 3 in 4.00 s, a little variation.
    return [[corner(1, 5.0 + 0.01 * (i % 3)), corner(2, 6.0 + 0.01 * (i % 2)), corner(3, 4.0 + 0.02 * (i % 2))]
            for i in range(n)]


def test_typical_is_the_median_of_recent_laps():
    t = typical_corners(usual())
    assert t[1]["time_s"] == 5.01 and t[1]["laps"] == 6 and t[1]["brake_m"] == 100 and t[1]["apex_gear"] == 3


def test_braking_early_is_named_as_the_cause():
    lap = [corner(1, 5.0), corner(2, 6.6, vmin=92, brake_m=125), corner(3, 4.0)]
    r = lap_review(lap, usual(), None, Model())
    assert [w["corner"] for w in r["wrong"]] == [2]
    w = r["wrong"][0]
    assert w["kind"] == "slow" and w["lost_s"] == 0.6
    assert "Braked 25 m earlier than your usual lap" in w["text"] or "8 km/h slower" in w["text"]


def test_a_spin_is_called_a_spin():
    lap = [corner(1, 5.0), corner(2, 9.5, vmin=30), corner(3, 4.0)]
    r = lap_review(lap, usual(), None, Model())
    assert r["wrong"][0]["kind"] == "spin" and "30 km/h" in r["wrong"][0]["text"]


def test_going_off_is_found_in_the_trace_and_put_with_its_corner():
    n = 1000
    trace = {"t": [i * 0.06 for i in range(n)], "p": [i / n for i in range(n)],
             "off": [4 if 405 <= i < 420 else 3 if 800 <= i < 805 else 0 for i in range(n)]}
    runs = off_track_runs(trace)
    assert [(r["wheels"], round(r["start_p"], 3)) for r in runs] == [(4, 0.405), (3, 0.8)]
    lap = [corner(1, 5.0), corner(2, 6.5), corner(3, 4.0)]
    r = lap_review(lap, usual(), trace, Model())
    kinds = [(w["kind"], w["corner"]) for w in r["wrong"]]
    assert ("off", 2) in kinds and ("off", None) in kinds  # Turn 2, and on the way to Turn 1
    t2 = next(w for w in r["wrong"] if w["corner"] == 2)
    assert "all four wheels" in t2["text"] and "lost 0.5 s" in t2["text"]


def test_good_corners_say_what_helped():
    lap = [corner(1, 4.7, vmin=106, brake_m=88), corner(2, 6.0), corner(3, 4.0)]
    r = lap_review(lap, usual(), None, Model())
    assert r["wrong"] == []
    assert [w["corner"] for w in r["well"]] == [1]
    assert r["well"][0]["text"].startswith("Your best ever here.")
    assert "faster at the slowest point" in r["well"][0]["text"] or "later than" in r["well"][0]["text"]


def test_normal_variation_isnt_a_mistake():
    lap = [corner(1, 5.05), corner(2, 6.05), corner(3, 4.05)]
    assert lap_review(lap, usual(), None, Model()) == {"wrong": [], "well": []}


def test_needs_a_few_laps_to_know_your_usual():
    lap = [corner(1, 9.0), corner(2, 6.0), corner(3, 4.0)]
    assert lap_review(lap, usual(2), None, Model())["wrong"] == []


def test_a_cut_lap_in_the_analysis_says_where_you_went_off(demo, clock, config, store):
    from pitwall_rig.rig import Rig

    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    while len(store.laps(limit=100)) < 10:
        clock.advance(1 / 60)
        rig.tick()
    cut = [lap for lap in store.laps(limit=100) if not lap["valid"] and not lap["out_lap"]]
    assert cut, "the demo driver didn't cut this time"
    reviews = [rig.corner_report(lap["id"])["review"] for lap in cut]
    assert all(r is not None for r in reviews)
    assert any(w["kind"] == "off" for r in reviews for w in r["wrong"])
