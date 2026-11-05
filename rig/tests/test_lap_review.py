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


def test_a_corner_counts_if_driven_all_the_way_and_clean():
    from pitwall_rig.analysis import counts

    assert counts({"driven": True, "clean": True}, lap_valid=False)  # good corner, cut elsewhere
    assert not counts({"driven": True, "clean": False}, lap_valid=True)
    assert not counts({"driven": False, "clean": None}, lap_valid=True)  # not driven (unfinished / jumped)
    assert counts({"driven": True, "clean": None}, lap_valid=True)  # old laps: go by the lap
    assert not counts({"driven": True, "clean": None}, lap_valid=False)
    assert counts({}, lap_valid=True)  # analysed before this was kept


def test_driven_through_needs_the_whole_corner_without_a_jump():
    from pitwall_rig.analysis import LapView, driven_through

    c = SimpleNamespace(number=1, label="T1", entry=0.30, apex=0.32, exit=0.34)
    n = 2000
    full = {"t": [i * 0.03 for i in range(n)], "p": [i / n for i in range(n)], "off": [0] * n}
    assert driven_through(LapView(full), c, 4000.0) == (True, True)
    stopped = {k: v[: int(0.33 * n)] for k, v in full.items()}  # quit mid-corner
    assert driven_through(LapView(stopped), c, 4000.0)[0] is False
    jumped = {k: [x for i, x in enumerate(v) if not (0.31 * n < i < 0.33 * n)] for k, v in full.items()}  # teleported past
    assert driven_through(LapView(jumped), c, 4000.0)[0] is False
    off = dict(full, off=[4 if 0.32 * n < i < 0.325 * n else 0 for i in range(n)])
    assert driven_through(LapView(off), c, 4000.0) == (True, False)


def test_an_unfinished_lap_counts_for_the_corners_it_drove(demo, clock, config, store):
    from pitwall_rig.models import Frame, GameStatus
    from pitwall_rig.rig import Rig

    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    while len([lap for lap in store.laps(limit=100) if lap["valid"]]) < 3:
        clock.advance(1 / 60)
        rig.tick()
    while rig.frame is None or rig.frame.lap_progress < 0.5:  # half a lap more...
        clock.advance(1 / 60)
        rig.tick()
    rig.laps.feed(Frame(t=clock(), status=GameStatus.OFF), rig.session)  # ...then quit
    lap = next(lap for lap in store.laps(limit=100) if lap["unfinished"])
    rep = rig.corner_report(lap["id"])
    driven = [c for c in rep["lap"] if c["driven"]]
    assert driven and len(driven) < len(rep["lap"])
    assert all(c.get("advice") is None for c in rep["lap"] if not c["driven"])
    # its well-driven corners are part of your history now (newest lap first)
    from pitwall_rig.analysis import counts

    counted = [c["corner"] for c in driven if counts(c, lap_valid=False)]
    assert counted
    hist = rig._history(rig._live_ctx())
    assert [c["corner"] for c in hist[0]] == counted


def _trace_with_slip(at_p, deg, seconds, n=4000, lap_s=100.0):
    tr = {"t": [lap_s * i / n for i in range(n)], "p": [i / n for i in range(n)], "off": [0] * n, "slip": [0.5] * n}
    i0 = int(at_p * n)
    for i in range(i0, i0 + int(seconds / lap_s * n)):
        tr["slip"][i] = deg
    return tr


def test_a_slide_you_caught_is_named_even_when_it_cost_nothing():
    lap = [corner(1, 5.0), corner(2, 6.0), corner(3, 4.0)]
    r = lap_review(lap, usual(), _trace_with_slip(0.415, 12.0, 0.6), Model())
    assert [(w["corner"], w["kind"]) for w in r["wrong"]] == [(2, "slide")]
    assert "12 degrees" in r["wrong"][0]["text"] and "caught it" in r["wrong"][0]["text"]
    # a short wobble isn't a slide; a car turned round is a spin
    assert lap_review(lap, usual(), _trace_with_slip(0.415, 12.0, 0.1), Model())["wrong"] == []
    spun = lap_review(lap, usual(), _trace_with_slip(0.415, 170.0, 2.0), Model())["wrong"]
    assert spun[0]["kind"] == "spin"


def test_wrong_gear_and_slow_on_the_power_are_named():
    lap = [corner(1, 5.3, gear=4, exit_kmh=140), corner(2, 6.3, throttle_m=45, exit_kmh=142), corner(3, 4.0)]
    kinds = {w["corner"]: w["kind"] for w in lap_review(lap, usual(), None, Model())["wrong"]}
    assert kinds == {1: "gear", 2: "throttle"}
