import ctypes as C

from pitwall_rig.adapters.ac import AssettoCorsaAdapter
from pitwall_rig.adapters.ac_structs import (
    AC_LIVE,
    AC_OFF,
    GRAPHICS_TAG,
    PHYSICS_TAG,
    STATIC_TAG,
    SPageFileGraphic,
    SPageFilePhysics,
    SPageFileStatic,
)
from pitwall_rig.models import GameStatus, Mode, SessionType, mode_for


def put_wstr(arr, text: str) -> None:
    for i, ch in enumerate(text.encode("utf-16-le")[::2]):
        arr[i] = ch


class FakePages:
    def __init__(self):
        self.phys = SPageFilePhysics()
        self.gfx = SPageFileGraphic()
        self.static = SPageFileStatic()

    def read(self, tag, size):
        obj = {PHYSICS_TAG: self.phys, GRAPHICS_TAG: self.gfx, STATIC_TAG: self.static}[tag]
        return bytes(obj)[:size]


def test_struct_sizes_match_kunos_layout():
    # Offsets of a few well-known fields in SharedFileOut.h (packed to 4 bytes).
    assert SPageFilePhysics.speedKmh.offset == 28
    assert SPageFilePhysics.wheelsPressure.offset == 32 + 12 + 12 + 16 + 16
    assert SPageFileGraphic.completedLaps.offset == 12 + 4 * 30
    assert SPageFileStatic.carModel.offset == 30 * 2 + 8
    assert C.sizeof(C.c_uint16 * 15) == 30


def test_off_when_game_not_running(clock):
    pages = FakePages()
    pages.gfx.status = AC_OFF
    ac = AssettoCorsaAdapter(reader=pages, clock=clock)
    f = ac.poll()
    assert f.status == GameStatus.OFF
    assert mode_for(f) == Mode.IDLE
    assert ac.session() is None


def test_reads_live_frame_and_session(clock):
    pages = FakePages()
    p, g, s = pages.phys, pages.gfx, pages.static
    p.packetId = 42
    p.gas, p.brake, p.speedKmh, p.gear, p.rpms = 0.8, 0.0, 212.5, 5, 7600  # gear 5 = 4th
    p.brakeBias = 0.575
    p.abs, p.tc = 0.25, 0.1
    for i, v in enumerate([27.1, 27.3, 26.8, 26.9]):
        p.wheelsPressure[i] = v
    g.status, g.session = AC_LIVE, 3
    g.completedLaps, g.iCurrentTime, g.iBestTime = 4, 61_234, 125_000
    g.normalizedCarPosition = 0.4
    g.carCoordinates[0], g.carCoordinates[2] = 120.5, -33.0
    g.sessionTimeLeft = -1
    put_wstr(s.carModel, "rss_formula_hybrid_2021")
    put_wstr(s.track, "ks_nordschleife")
    put_wstr(s.trackConfiguration, "touristenfahrten")
    s.trackSPlineLength = 20832.0

    ac = AssettoCorsaAdapter(reader=pages, clock=clock)
    f = ac.poll()
    assert f.status == GameStatus.LIVE
    assert f.gear == 4
    assert round(f.speed_kmh, 1) == 212.5
    assert round(f.brake_bias, 3) == 0.575
    assert [round(x, 1) for x in f.tyre_pressure_psi] == [27.1, 27.3, 26.8, 26.9]
    assert f.lap == 4 and f.lap_time_ms == 61_234 and f.best_lap_ms == 125_000
    assert f.world[0] == 120.5 and f.world[2] == -33.0
    assert f.session_time_left_s is None
    assert mode_for(f) == Mode.DRIVING

    info = ac.session()
    assert info.car == "rss_formula_hybrid_2021"
    assert info.track_key == "ks_nordschleife@touristenfahrten"
    assert info.session_type == SessionType.HOTLAP
    assert info.track_length_m == 20832.0


def test_pit_box_is_analysis_mode(clock):
    pages = FakePages()
    pages.gfx.status = AC_LIVE
    pages.gfx.isInPit = 1
    f = AssettoCorsaAdapter(reader=pages, clock=clock).poll()
    assert f.in_pit_box and mode_for(f) == Mode.ANALYSIS


def test_brake_bias_zero_means_unknown(clock):
    pages = FakePages()
    pages.gfx.status = AC_LIVE
    assert AssettoCorsaAdapter(reader=pages, clock=clock).poll().brake_bias is None


def test_missing_pages_mean_game_off(clock):
    class Nothing:
        def read(self, tag, size):
            return None

    ac = AssettoCorsaAdapter(reader=Nothing(), clock=clock)
    assert ac.poll().status == GameStatus.OFF
    assert ac.session() is None


def test_frozen_live_page_is_treated_as_closed(clock):
    pages = FakePages()
    pages.gfx.status = AC_LIVE
    pages.phys.packetId = 10
    resets = []
    pages.reset = lambda: resets.append(1)
    ac = AssettoCorsaAdapter(reader=pages, clock=clock, stale_after_s=3.0)
    assert ac.poll().status == GameStatus.LIVE
    clock.advance(2.0)
    assert ac.poll().status == GameStatus.LIVE
    clock.advance(2.0)  # packet id hasn't moved for 4 s: AC has quit
    assert ac.poll().status == GameStatus.OFF
    assert resets
    pages.phys.packetId = 11  # AC is back
    clock.advance(0.1)
    assert ac.poll().status == GameStatus.LIVE
