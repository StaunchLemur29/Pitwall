"""The SF1000 wheel screen: F1 23 UDP packets built from Pitwall's data."""

import struct

from pitwall_rig.models import Frame, GameStatus, SessionInfo
from pitwall_rig.sf1000 import HEADER, LAP, STATUS, TELEMETRY, Sf1000

SESSION = SessionInfo(game="ac", car="rss_formula", track="nordschleife", max_rpm=12000, track_length_m=20832,
                      max_fuel_l=110)


class FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


def frame(**kw):
    base = {"t": 12.5, "status": GameStatus.LIVE, "gear": 4, "rpm": 11500, "speed_kmh": 243.4, "gas": 1.0, "brake": 0.0,
                "fuel_l": 42.5, "brake_bias": 0.57, "abs": 3, "tc": 2, "lap": 2, "lap_time_ms": 61_234, "last_lap_ms": 478_901,
                "lap_progress": 0.25, "sector": 1, "drs_open": True, "tyre_core_temp_c": [85.0, 86.0, 80.0, 81.0],
                "tyre_pressure_psi": [27.1, 27.2, 26.1, 26.2]}
    base.update(kw)
    return Frame(**base)


def test_packet_sizes_match_the_f1_23_spec():
    w = Sf1000("10.0.0.5", sock=FakeSock())
    f = frame()
    sizes = {k: len(getattr(w, k)(f, SESSION, 1.0)) for k in ("session", "lap", "participants", "telemetry", "status", "damage")}
    assert sizes == {"session": 644, "lap": 1131, "participants": 1306, "telemetry": 1352, "status": 1239, "damage": 953}


def test_header_and_your_car_carry_the_right_values():
    w = Sf1000("10.0.0.5", sock=FakeSock())
    pkt = w.telemetry(frame(), SESSION, 3.0)
    fmt, year, _major, _minor, _ver, pid, _uid, _t, _fid, _ofid, me, second = HEADER.unpack_from(pkt)
    assert (fmt, year, pid, me, second) == (2023, 23, 6, 0, 255)
    car = TELEMETRY.unpack_from(pkt, HEADER.size)
    speed, _throttle, _steer, _brake, _clutch, gear, rpm, drs, rev = car[:9]
    assert (speed, gear, rpm, drs) == (243, 4, 11500, 1)
    assert 0 < rev <= 100  # 11500 of 12000 rpm: most of the lights
    pressures = car[-8:-4]
    assert [round(x, 1) for x in pressures] == [26.1, 26.2, 27.1, 27.2]  # rear-left, rear-right, front-left, front-right
    status = STATUS.unpack_from(w.status(frame(), SESSION, 3.0), HEADER.size)
    assert status[:4] == (2, 1, 0, 57)  # TC full, ABS on, fuel mix, brake bias 57 %
    assert round(status[5], 1) == 42.5 and round(status[6]) == 110
    lap = LAP.unpack_from(w.lap(frame(), SESSION, 3.0), HEADER.size)
    assert lap[0] == 478_901 and lap[1] == 61_234 and lap[12] == 3  # last, current, lap number


def test_session_says_km_h_and_celsius():
    w = Sf1000("10.0.0.5", sock=FakeSock())
    body = w.session(frame(), SESSION, 1.0)[HEADER.size:]
    track_length = struct.unpack_from("<H", body, 4)[0]
    assert track_length == 20832
    assert body[601] == 7 and body[602] == 1  # game mode, rule set
    assert body[608] == 1 and body[609] == 0  # speed in km/h, temperature in C


def test_sends_what_is_due_and_nothing_when_the_game_is_off():
    sock = FakeSock()
    w = Sf1000("10.0.0.5", sock=sock)
    assert w.send(frame(), SESSION, now=0.0) == 6  # everything at first
    assert w.send(frame(), SESSION, now=0.016) == 3  # then telemetry, status and lap every frame
    assert w.send(frame(), SESSION, now=0.6) == 5  # plus session (2 Hz) and damage (10 Hz)
    assert {addr for _, addr in sock.sent} == {("10.0.0.5", 20777)}
    assert w.send(Frame(t=0, status=GameStatus.OFF), SESSION, now=1.0) == 0


def test_a_wheel_that_isnt_there_doesnt_break_anything():
    class Down:
        def sendto(self, *a):
            raise OSError("Network is unreachable")

    w = Sf1000("10.0.0.5", sock=Down())
    assert w.send(frame(), SESSION, now=0.0) == 0 and "unreachable" in w.error


def test_rig_feeds_the_wheel_when_switched_on(demo, clock, config, store, monkeypatch):
    from pitwall_rig import sf1000 as mod
    from pitwall_rig.rig import Rig

    sock = FakeSock()
    monkeypatch.setattr(mod.socket, "socket", lambda *a: sock)
    rig = Rig(demo, store, config, emit=lambda e: None, clock=clock)
    for _ in range(30):
        clock.advance(1 / 60)
        rig.tick()
    assert sock.sent == [] and rig.sf1000_status()["enabled"] is False  # off by default
    rig.config.update({"sf1000": {"enabled": True, "ip": "192.168.1.50", "port": 20777}})
    for _ in range(30):
        clock.advance(1 / 60)
        rig.tick()
    assert sock.sent and {a for _, a in sock.sent} == {("192.168.1.50", 20777)}
    assert rig.sf1000_status()["sent"] == len(sock.sent)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    out = rig.sf1000_test()
    assert out["ok"] and out["sent"] > 10
