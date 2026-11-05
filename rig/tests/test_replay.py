from pitwall_rig.adapters.replay import Recorder, ReplayAdapter
from pitwall_rig.models import GameStatus


def test_record_then_replay(tmp_path, demo, clock):
    path = tmp_path / "s.pwrec"
    rec = Recorder(path, "demo", demo.capabilities)
    for _ in range(600):
        clock.advance(1 / 60)
        rec.add(demo.poll(), demo.session())
    rec.close()

    rclock = type(clock)(100.0)
    rp = ReplayAdapter(path, clock=rclock)
    assert rp.game_id == "demo" and rp.capabilities.reports_brake_bias
    first = rp.poll()
    assert first.status == GameStatus.LIVE
    assert rp.session().car == "demo_gt3"
    rclock.advance(5.0)
    later = rp.poll()
    assert later.packet_id > first.packet_id
    rclock.advance(20.0)  # past the end: loops
    looped = rp.poll()
    assert looped.packet_id > later.packet_id  # ids stay unique across loops


def test_recording_survives_being_killed(tmp_path, demo, clock):
    """Closing the window skips close(); flushed data must still replay."""
    path = tmp_path / "killed.pwrec"
    rec = Recorder(path, "demo", demo.capabilities, flush_every_s=1.0, clock=clock)
    for _ in range(300):
        clock.advance(1 / 60)
        rec.add(demo.poll(), demo.session())
    # no rec.close(): simulate the process being killed
    rp = ReplayAdapter(path, clock=type(clock)(0.0))
    assert rp._duration > 3.0  # at least the flushed seconds are there


def test_real_ac_recording_yields_a_valid_lap():
    """One real lap of Spa from Assetto Corsa (RSS GT-M Mercer V8), recorded with Pitwall."""
    from pathlib import Path

    from pitwall_rig.laps import LapRecorder

    path = Path(__file__).parent / "fixtures" / "ac_spa_one_lap.pwrec"
    t = [0.0]
    rp = ReplayAdapter(path, clock=lambda: t[0], loop=False)
    laps = []
    rec = LapRecorder(laps.append, wall_clock=lambda: t[0])
    while t[0] < rp._duration + 2:
        t[0] += 1 / 60
        rec.feed(rp.poll(), rp.session())
    # The clip starts 3 s before the line, so the first "lap" is a partial one.
    assert [lap.lap_time_ms for lap in laps] == [149045, 148252]
    assert laps[0].out_lap and not laps[0].valid
    lap = laps[1]
    assert lap.valid and not lap.out_lap
    assert lap.track_key == "spa@2022"
    assert len(lap.sector_ms) == 3 and sum(lap.sector_ms) == 148252


def test_real_time_shift_rewind_is_never_a_teleport():
    """A Time Shift rewind from the rig (Spa): AC moves the car back a few metres
    a frame but only updates lap progress every few frames. It must read as a
    rewind all the way, never a teleport (which would make the lap an out lap)."""
    from pathlib import Path

    from pitwall_rig.laps import REWIND, TELEPORT, JumpDetector

    path = Path(__file__).parent / "fixtures" / "ac_spa_timeshift.pwrec"
    t = [0.0]
    rp = ReplayAdapter(path, clock=lambda: t[0], loop=False)
    jd = JumpDetector()
    seen = []
    while t[0] < rp._duration:
        t[0] += 1 / 60
        f = rp.poll()
        if f.status == GameStatus.LIVE:
            j = jd.step(f)
            if j:
                seen.append(j)
    assert seen.count(REWIND) > 10
    assert TELEPORT not in seen
