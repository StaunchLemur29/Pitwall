"""Real moments from the rig (Spa, 100 % damage, 5x tyre wear), played back
through Pitwall, so what the coach says about them can't quietly change."""

import itertools
from pathlib import Path

from pitwall_rig.adapters.replay import ReplayAdapter
from pitwall_rig.config import Config
from pitwall_rig.models import GameStatus
from pitwall_rig.rig import Rig
from pitwall_rig.storage import Store

FIX = Path(__file__).parent / "fixtures"


def play(name, tmp_path, on_tick=None):
    t = [0.0]
    rig = Rig(ReplayAdapter(FIX / name, clock=lambda: t[0], loop=False), Store(tmp_path / "p.sqlite"),
              Config(tmp_path / "c.json"), emit=lambda e: None, clock=lambda: t[0])
    texts = []
    while t[0] < rig.adapter._duration + 1:
        t[0] += 1 / 60
        rig.tick()
        n = rig.conditions.notice
        if n and (not texts or texts[-1] != n["text"]):
            texts.append(n["text"])
        if on_tick:
            on_tick(rig)
    return rig, texts


def test_a_crash_is_one_notice_that_says_what_it_damaged(tmp_path):
    """Off at speed into the barrier: damage on two sides, dirty tyres, a stop."""
    _, texts = play("ac_spa_crash.pwrec", tmp_path)
    crash = [x for x in texts if x.startswith(("Crash", "Crashed"))]
    assert crash, texts
    final = crash[-1]
    assert "left" in final and "rear" in final and "tyres cooler" in final, final
    # one incident: it grows as the crash goes on, it doesn't start over
    assert all(x.startswith("Crash") for x in crash)
    assert not any("Dirty tyres" in x for x in texts[texts.index(crash[0]):])  # the crash covers it


def test_return_to_pits_reads_the_car_from_the_track_not_the_reset(tmp_path):
    """AC's "return to pits" resets the car before Pitwall sees the pits: the pit
    report must use the damage, fuel and wear from the last moment on track."""
    captured = {}

    def grab(rig):
        if not captured and rig._in_pits:
            captured["end"] = getattr(rig, "_last_track_snap", None)
            captured["frame_damage"] = rig.frame.damage

    _, _ = play("ac_spa_return_to_pits.pwrec", tmp_path, grab)
    assert captured, "never got to the pits"
    assert max(captured["frame_damage"]) == 0  # the reset car, as AC shows it in the pits
    end = captured["end"]
    assert end and end["damage"] and end["damage"] > 100  # the car as it was out on track
    assert end["fuel_l"] < 45


def test_pausing_doesnt_count_as_driving(tmp_path):
    """The clip pauses in the gravel: paused frames aren't a crash, a jump or a lap."""
    statuses = set()
    rig, _ = play("ac_spa_return_to_pits.pwrec", tmp_path, lambda r: statuses.add(r.frame.status))
    assert GameStatus.PAUSED in statuses
    assert rig.store.laps(limit=10) == [] or all(not lap["valid"] for lap in rig.store.laps(limit=10))


def test_a_real_lap_ends_at_the_line_and_the_optimal_run_can_learn_from_it(tmp_path):
    """AC resets the lap clock a frame before it counts the lap. That sample is
    the start of the next lap: left on the end of this one, time ran backwards
    there and the optimal run couldn't learn the car from any real lap."""
    from pitwall_rig.optimal_run import learn_grip

    rig, _ = play("ac_spa_one_lap.pwrec", tmp_path)
    lap = next(l for l in rig.store.laps("ac", "spa@2022", "rss_gtmx_mercer_extreme_v8") if l["valid"])
    tr = rig.store.trace(lap["id"])
    assert all(b >= a for a, b in itertools.pairwise(tr["t"]))  # time only runs forwards
    assert tr["t"][0] < 0.05  # and the lap has its own first sample
    assert abs(tr["t"][-1] * 1000 - lap["lap_time_ms"]) < 100
    grip = learn_grip([tr])
    assert grip is not None
    g = grip.to_dict()
    assert 1.2 < g["lat_g_100"] < 2.2 and 1.3 < g["brake_g_100"] < 2.3 and 250 < g["top_kmh"] < 280
    assert grip.gear(60 / 3.6) < grip.gear(250 / 3.6)  # the gear you pull at each speed


def test_laps_saved_with_the_stray_sample_are_cleaned_when_read(tmp_path):
    from pitwall_rig.laps import next_lap_tail

    tr = {"t": [147.9, 148.0, 148.1, 0.001, 0.02], "p": [0.99, 0.995, 0.0002, 0.0003, 0.0005]}
    assert next_lap_tail(tr) == 2
    assert next_lap_tail({"t": [10.0, 10.1, 4.0, 4.1], "p": [0.2, 0.21, 0.1, 0.11]}) == 0  # a rewind early in a lap
    assert next_lap_tail({"t": [50.0, 50.1, 40.0, 40.1], "p": [0.5, 0.51, 0.4, 0.41]}) == 0
    assert next_lap_tail({"t": [1.0, 1.1, 1.2], "p": [0.1, 0.2, 0.3]}) == 0
