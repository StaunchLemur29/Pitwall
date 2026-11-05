from types import SimpleNamespace

from pitwall_rig.scan import blind_spots

C = [SimpleNamespace(number=n, label=f"Turn {n}", grade=3) for n in (1, 2, 3)]
P = [SimpleNamespace(number=1, name="Turns 1 to 3", corners=[1, 2, 3])]


def lap(brake=100, throttle=20, coast=0.0, gear=3):
    return [{"corner": n, "time_s": 5.0, "brake_m": brake, "throttle_m": throttle, "coast_s": coast, "apex_gear": gear}
            for n in (1, 2, 3)]


OPT = {n: {"brake_m": 80, "throttle_m": 10, "apex_gear": 3} for n in (1, 2, 3)}


def test_habits_are_found_with_where_and_a_drill():
    laps = [lap(brake=100, coast=0.5) for _ in range(8)]
    found = {f["key"]: f for f in blind_spots(laps, C, OPT, None, P)}
    assert "brake_early" in found and "coasting" in found
    assert found["brake_early"]["drill"] == {"number": 1, "name": "Turns 1 to 3"}
    assert "20 m before" in found["brake_early"]["detail"]


def test_one_offs_and_too_few_laps_say_nothing():
    assert blind_spots([lap(brake=100) for _ in range(3)], C, OPT, None, P) == []  # not enough laps
    mostly_fine = [lap(brake=82) for _ in range(9)] + [lap(brake=110)]
    assert blind_spots(mostly_fine, C, OPT, None, P) == []  # once isn't a habit


def test_abrupt_brake_release_from_the_pedal_check():
    assert blind_spots([lap(brake=82) for _ in range(3)], C, OPT, {"abrupt_pct": 55}, P) == []  # too few laps yet
    found = blind_spots([lap(brake=82) for _ in range(8)], C, OPT, {"abrupt_pct": 55}, P)
    assert [f["key"] for f in found] == ["brake_release"]
    assert blind_spots([lap(brake=82) for _ in range(8)], C, OPT, {"abrupt_pct": 20}, P) == []  # the rig's 20 %: fine
