import math

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
                    lap_time_ms=int(prog * lap_s * 1000),
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
    for _ in range(60 * 240):
        clock.advance(1 / 60)
        rec.feed(demo.poll(), demo.session())
    assert len(laps) >= 3
    assert laps[0].out_lap  # starts in the pit box
    assert any(lap.valid for lap in laps[1:])
    for lap in laps:
        assert 40_000 < lap.lap_time_ms < 90_000


# -- practice: teleports and rewinds -------------------------------------------

LENGTH_M = 4000.0


class Driver:
    """Drives a 4 km round track at a steady speed, frame by frame, with real positions."""

    def __init__(self, rec, kmh=200.0, hz=60):
        self.rec, self.kmh, self.hz = rec, kmh, hz
        self.t, self.packet, self.lap, self.lap_ms, self.p, self.last_ms = 0.0, 0, 0, 0.0, 0.0, 0
        self.tyres_out = 0

    def frame(self, status=GameStatus.LIVE):
        self.packet += 1
        r = LENGTH_M / (2 * math.pi)  # a round track
        a = 2 * math.pi * self.p
        self.rec.feed(Frame(t=self.t, status=status, packet_id=self.packet, lap=self.lap, lap_time_ms=int(self.lap_ms),
                            last_lap_ms=self.last_ms, lap_progress=self.p, speed_kmh=self.kmh, tyres_out=self.tyres_out,
                            sector=min(2, int(self.p * 3)),
                            world=(r * math.cos(a), 0.0, r * math.sin(a))),
                      SESSION)

    def drive_to(self, p_end):
        step_s = 1 / self.hz
        step_p = self.kmh / 3.6 * step_s / LENGTH_M
        while self.p < p_end:
            self.t += step_s
            self.lap_ms += step_s * 1000
            self.p = min(1.0, self.p + step_p)
            if self.p >= 1.0:  # over the line
                self.last_ms, self.lap, self.lap_ms, self.p = int(self.lap_ms), self.lap + 1, 0.0, 0.0
                self.frame()
                return
            self.frame()

    def lap_from_line(self):
        self.drive_to(1.0)


def test_full_speed_laps_are_not_mistaken_for_jumps():
    laps = []
    d = Driver(LapRecorder(laps.append), kmh=330)
    d.lap_from_line()
    d.lap_from_line()
    d.drive_to(0.05)  # identical lap times: the recorder waits a second for AC's lap time
    assert [lap.valid for lap in laps] == [True, True]


def test_teleport_forward_doesnt_make_a_fake_fast_lap():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.drive_to(0.2)
    d.p, d.t = 0.9, d.t + 1 / 60  # teleport most of the way round
    d.frame()
    d.lap_from_line()
    d.drive_to(0.01)
    assert len(laps) == 1
    assert laps[0].lap_time_ms < 40_000  # AC would time it as a lap...
    assert not laps[0].valid and laps[0].out_lap  # ...but it never counts


def test_a_rewind_after_a_mistake_is_a_normal_lap_but_never_a_best():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.drive_to(0.35)  # into sector 2
    d.tyres_out = 4
    d.drive_to(0.38)  # went off...
    d.tyres_out = 0
    for _ in range(30):  # ...Time Shift: the game isn't live while it rewinds
        d.t += 1 / 60
        d.frame(GameStatus.REPLAY)
    d.p, d.lap_ms = 0.30, d.lap_ms - 6000  # back to before the mistake, in sector 1 again
    d.frame()
    d.lap_from_line()
    d.drive_to(0.01)
    assert len(laps) == 1
    lap = laps[0]
    assert lap.valid and lap.rewound and not lap.out_lap  # the cut was rewound away
    ps = lap.trace["p"]
    assert all(b > a for a, b in zip(ps, ps[1:], strict=False))  # the erased bit is gone
    assert len(lap.sector_ms) == 3 and sum(lap.sector_ms) == lap.lap_time_ms


def test_rewinding_in_a_drill_is_practice_not_a_lap():
    laps = []
    rec = LapRecorder(laps.append)
    d = Driver(rec)
    d.drive_to(0.5)
    rec.practising = True
    d.p = 0.42
    d.frame()
    d.lap_from_line()
    d.drive_to(0.01)
    assert len(laps) == 1 and laps[0].out_lap and not laps[0].valid and not laps[0].rewound


def test_rewinding_back_over_the_line_leaves_no_stray_lap():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.lap_from_line()
    d.drive_to(0.02)
    d.lap, d.p, d.lap_ms = 0, 0.98, 59_000.0  # Time Shift back into the last lap
    d.frame()
    d.lap_from_line()  # over the line again
    d.lap_from_line()  # and a full lap
    d.drive_to(0.01)
    assert [(lap.valid, lap.out_lap) for lap in laps] == [(True, False), (True, False)]


def test_pausing_doesnt_invalidate_a_lap():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.drive_to(0.5)
    for _ in range(600):  # ten seconds in the pause menu
        d.t += 1 / 60
        d.frame(GameStatus.PAUSED)
    d.lap_from_line()
    d.drive_to(0.01)
    assert len(laps) == 1 and laps[0].valid


def test_the_lap_after_a_teleport_counts_again():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.drive_to(0.3)
    d.p = 0.95
    d.frame()
    d.lap_from_line()  # the teleported lap
    d.lap_from_line()  # a proper one
    d.drive_to(0.01)
    assert [lap.valid for lap in laps] == [False, True]


def test_a_lap_you_quit_is_kept_as_unfinished():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.lap_from_line()
    d.drive_to(0.4)  # then back to the menu mid-lap
    d.t += 1 / 60
    d.rec.feed(Frame(t=d.t, status=GameStatus.OFF, packet_id=d.packet + 1), SESSION)
    assert len(laps) == 2
    lap = laps[1]
    assert lap.unfinished and lap.out_lap and not lap.valid
    assert 0.39 < max(lap.trace["p"]) <= 0.41


def test_a_restart_keeps_what_you_drove_but_not_a_few_metres():
    laps = []
    d = Driver(LapRecorder(laps.append))
    d.drive_to(0.01)  # barely moved
    d.lap, d.p, d.lap_ms = -1, 0.0, 0.0  # session restarted (lap counter went back)
    d.frame()
    assert laps == []
    d.lap = 0
    d.drive_to(0.3)
    d.lap, d.p, d.lap_ms = -1, 0.0, 0.0
    d.frame()
    assert len(laps) == 1 and laps[0].unfinished
