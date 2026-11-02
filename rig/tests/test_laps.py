from pitwall_rig.laps import LapRecorder
from pitwall_rig.models import Frame, GameStatus, SessionInfo

SESSION = SessionInfo(game="ac", car="car_a", track="spa")


def drive(rec, start_lap=0, laps=1, lap_s=60.0, hz=60, t0=0.0, start_progress=0.0, tyres_out_at=None, last_ms_lag=0):
    """Feed synthetic frames for whole laps. Returns end time."""
    t = t0
    packet = int(t0 * hz)
    last_ms = 0
    for lap in range(start_lap, start_lap + laps):
        n = int(lap_s * hz)
        for i in range(n):
            prog = start_progress + (1 - start_progress) * i / n if lap == start_lap else i / n
            packet += 1
            t += 1 / hz
            rec.feed(
                Frame(
                    t=t,
                    status=GameStatus.LIVE,
                    packet_id=packet,
                    lap=lap,
                    lap_time_ms=int(i / hz * 1000),
                    last_lap_ms=last_ms,
                    lap_progress=prog,
                    sector=min(2, int(prog * 3)),
                    tyres_out=3 if tyres_out_at is not None and abs(prog - tyres_out_at) < 0.01 else 0,
                    world=(prog * 100, 0, 0),
                ),
                SESSION,
            )
        last_ms = int(lap_s * 1000)
    # cross the line: next lap starts, last_lap updates (possibly a few frames later)
    for j in range(max(1, last_ms_lag + 1)):
        packet += 1
        t += 1 / hz
        rec.feed(
            Frame(
                t=t, status=GameStatus.LIVE, packet_id=packet, lap=start_lap + laps,
                lap_time_ms=j * 16, last_lap_ms=last_ms if j >= last_ms_lag else 0, lap_progress=0.0,
            ),
            SESSION,
        )
    return t


def test_records_a_clean_lap():
    laps = []
    drive(LapRecorder(laps.append), laps=1, lap_s=30)
    assert len(laps) == 1
    lap = laps[0]
    assert lap.lap_time_ms == 30_000 and lap.valid and not lap.out_lap
    assert lap.lap_number == 1
    assert len(lap.sector_ms) == 3 and sum(lap.sector_ms) == 30_000
    assert len(lap.trace["t"]) == 30 * 60


def test_cut_invalidates_lap():
    laps = []
    drive(LapRecorder(laps.append), laps=1, lap_s=20, tyres_out_at=0.5)
    assert laps and not laps[0].valid


def test_joining_mid_lap_is_flagged():
    laps = []
    drive(LapRecorder(laps.append), laps=1, lap_s=20, start_progress=0.5)
    assert laps[0].out_lap and not laps[0].valid


def test_waits_for_last_lap_time_to_update():
    laps = []
    drive(LapRecorder(laps.append), laps=1, lap_s=20, last_ms_lag=5)
    assert laps[0].lap_time_ms == 20_000


def test_paused_frames_are_not_recorded():
    laps = []
    rec = LapRecorder(laps.append)
    rec.feed(Frame(t=0, status=GameStatus.PAUSED, packet_id=1), SESSION)
    rec.feed(Frame(t=0, status=GameStatus.OFF), SESSION)
    assert laps == []


def test_demo_produces_several_laps(demo, clock):
    laps = []
    rec = LapRecorder(laps.append, wall_clock=clock)
    for _ in range(60 * 200):
        clock.advance(1 / 60)
        rec.feed(demo.poll(), demo.session())
    assert len(laps) >= 3
    assert laps[0].out_lap  # starts in the pit box
    assert any(lap.valid for lap in laps[1:])
    for lap in laps:
        assert 40_000 < lap.lap_time_ms < 90_000
