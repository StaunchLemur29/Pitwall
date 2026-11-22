from pitwall_rig.tips import Tips


def w(corner, kind, text="Something. More."):
    return {"corner": corner, "label": f"Turn {corner}", "kind": kind, "text": text, "lost_s": 0.2}


def test_a_repeated_mistake_beats_the_focus():
    t = Tips()
    t.add_lap([w(3, "gear", "Gear 3 at the apex; you usually use 2. Lost 0.3 s.")])
    t.add_lap([w(5, "slow")])
    t.add_lap([w(3, "gear", "Gear 3 at the apex; you usually use 2. Lost 0.2 s.")])
    tip = t.pick({"corner": 7, "label": "Turn 7", "fix": "Brake later."})
    assert tip["corner"] == 3 and tip["text"].startswith("Gear 3 at the apex") and "2 of your last 3 laps" in tip["text"]
    assert "Lost" not in tip["text"]  # the first sentence only


def test_without_repeats_the_focus_fix_is_the_tip():
    t = Tips()
    t.add_lap([w(5, "slow")])
    assert t.pick({"corner": 7, "label": "Turn 7", "fix": "Brake 10 m later."})["corner"] == 7
    assert t.pick(None) is None


def test_shown_once_a_lap_on_the_straight_before_its_corner():
    t = Tips()
    focus = {"corner": 7, "label": "Turn 7", "fix": "Brake 10 m later."}
    assert t.live(1, 7, 800.0, 0.0, focus, quiet=False) is None  # too far
    assert t.live(1, 6, 400.0, 1.0, focus, quiet=False) is None  # another corner first
    assert t.live(1, 7, 400.0, 2.0, focus, quiet=False)["corner"] == 7
    assert t.live(1, 7, 300.0, 3.0, focus, quiet=False) is not None  # stays up...
    assert t.live(1, 7, 10.0, 4.0, focus, quiet=False) is None  # ...until the corner
    assert t.live(1, 7, 400.0, 50.0, focus, quiet=False) is None  # once a lap
    assert t.live(2, 7, 400.0, 99.0, focus, quiet=True) is None  # not over a drill / notice
    assert t.live(2, 7, 400.0, 100.0, focus, quiet=False) is not None  # next lap


def test_on_linked_corners_the_tip_comes_on_the_straight_before_the_run():
    t = Tips()
    focus = {"corner": 7, "label": "Turn 7", "fix": "Brake later."}
    approach = {7: 6}.get  # Turn 7 follows Turn 6 too closely to read a tip in between
    assert t.live(1, 7, 100.0, 0.0, focus, quiet=False, approach=lambda c: approach(c, c)) is None
    assert t.live(1, 6, 400.0, 1.0, focus, quiet=False, approach=lambda c: approach(c, c))["corner"] == 7


def test_differences_become_instructions_and_good_ones_are_skipped():
    from pitwall_rig.tips import as_instruction

    assert as_instruction("Braked 12 m earlier than your best lap.") == "Brake 12 m later."
    assert as_instruction("Gear 3 at the apex; your best lap used 2.") == "Use gear 2 at the apex, not 3."
    assert as_instruction("6 km/h slower at the slowest point than your best lap.") == "Carry 6 km/h more to the apex."
    assert as_instruction("Back to full throttle 126 m earlier than your best lap.") is None  # that's better
    assert as_instruction("4 km/h faster on the exit than your best lap.") is None


def test_drs_left_shut_on_two_laps_becomes_a_tip_on_that_straight():
    from types import SimpleNamespace

    from pitwall_rig.tips import systems_mistakes

    corner = SimpleNamespace(number=5, label="Turn 5")
    model = SimpleNamespace(next_corner=lambda p: (corner, 120.0))
    systems = {"drs": {"open_m": 0, "missed": [{"start_p": 0.30, "end_p": 0.36, "metres": 310, "near": "before Turn 5"}]},
               "battery": {"empty": [{"start_p": 0.5, "end_p": 0.52, "metres": 120, "near": "before Turn 5"}]}}
    slips = systems_mistakes(systems, model)
    assert [(s["kind"], s["corner"]) for s in slips] == [("drs", 5), ("battery", 5)]
    assert systems_mistakes(None, model) == [] and systems_mistakes({"drs": None, "battery": None}, model) == []

    t = Tips()
    t.add_lap(slips[:1])
    t.add_lap([])
    t.add_lap(slips[:1])
    tip = t.pick(None)
    assert tip["corner"] == 5 and tip["kind"] == "drs"
    assert tip["text"] == "Open the DRS on the way to Turn 5. (2 of your last 3 laps.)"
