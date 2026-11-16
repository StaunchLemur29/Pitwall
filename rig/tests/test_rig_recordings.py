"""Real moments from the rig (Spa, 100 % damage, 5x tyre wear), played back
through Pitwall, so what the coach says about them can't quietly change."""

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
