"""The session timer: stint, time since a break, what's left of a race."""

from pitwall_rig.models import Frame, GameStatus, SessionType
from pitwall_rig.rig import Rig


def run(rig, clock, seconds):
    for _ in range(int(seconds * 10)):
        clock.advance(0.1)
        rig.tick()


def test_stint_and_break_reminder(demo, clock, config, store):
    config.update({**config.data, "session_timer": {"break_reminder_min": 1}})
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    run(rig, clock, 30)
    t = rig.live()["timer"]
    assert 20 < t["stint_s"] <= 30 and not t["break_due"] and t["race"] is None
    run(rig, clock, 60)
    # Due now, but only said where it's safe to read: never in or just before a corner.
    said, hidden = 0, 0
    for _ in range(600):
        clock.advance(0.1)
        rig.tick()
        nc = rig.track.model.next_corner(rig.frame.lap_progress)
        due = rig.live()["timer"]["break_due"]
        if due:
            said += 1
            assert nc[1] >= 150
        else:
            hidden += 1
    assert said and hidden

    # Five minutes out of the car is a break: the count starts again.
    off = rig.adapter.poll
    rig.adapter.poll = lambda: Frame(t=clock(), status=GameStatus.OFF)
    run(rig, clock, 301)
    rig.adapter.poll = off
    run(rig, clock, 5)
    t = rig.live()["timer"]
    assert t["since_break_s"] < 10 and not t["break_due"]


def test_off_by_default(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    run(rig, clock, 200)
    assert config["session_timer"]["break_reminder_min"] == 0
    assert not rig.live()["timer"]["break_due"]


def test_a_race_shows_laps_left_or_time_left(demo, clock, config, store):
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    run(rig, clock, 5)
    rig.session.session_type = SessionType.RACE
    rig.frame.position, rig.frame.session_laps, rig.frame.lap = 3, 10, 4
    assert rig._timer_live()["race"] == {"position": 3, "laps_left": 6, "time_left_s": None}
    rig.frame.session_laps, rig.frame.session_time_left_s = 0, 754.0  # a timed race
    assert rig._timer_live()["race"] == {"position": 3, "laps_left": None, "time_left_s": 754.0}
