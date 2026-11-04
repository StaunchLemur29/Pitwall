"""Thrustmaster SF1000 wheel screen, fed by Pitwall over Wi-Fi.

The SF1000 joins your Wi-Fi and, in its UDP mode, listens on port 20777 for
packets in the F1 23 game's telemetry format (see docs/research/sf1000-screen.md:
Thrustmaster's USB route isn't open to other programs). Pitwall sends those
packets itself, filled from Assetto Corsa's data, so the wheel's own F1 pages
work in AC: gear, speed, RPM and rev lights, lap and sector times, fuel, tyres,
brake bias, ABS / TC, DRS.

The layouts follow the F1 23 UDP specification (little-endian, packed), checked
against the MIT-licensed SimHub-SF1000-UDP plugin's structures: header 29 bytes,
lap data 1131, telemetry 1352, status 1239, session 644, damage 953,
participants 1306. Only car 0 (you) is filled.
"""

from __future__ import annotations

import socket
import struct
import time
from typing import Any

from .models import Frame, GameStatus, SessionInfo

PORT = 20777
CARS = 22

HEADER = struct.Struct("<HBBBBBQfIIBB")  # 29
TELEMETRY = struct.Struct("<HfffBbHBBH4H4B4BH4f4B")  # 60 per car
TELEMETRY_TAIL = struct.Struct("<BBb")  # mfd panel, secondary, suggested gear
STATUS = struct.Struct("<BBBBBfffHHBBHBBBbfffBfffB")  # 55 per car
LAP = struct.Struct("<IIHBHBHHfffBBBBBBBBBBBBBBBHHB")  # 50 per car
LAP_TAIL = struct.Struct("<BB")  # time-trial PB / rival car index
SESSION_HEAD = struct.Struct("<BbbBHBbBHHBBBBBB")  # 19 bytes before the marshal zones
SESSION_LEN = 615  # the session body after the header
DAMAGE = struct.Struct("<4f4B4B18B")  # 42 per car
PARTICIPANT_LEN = 58

IDS = {"session": 1, "lap": 2, "participants": 4, "telemetry": 6, "status": 7, "damage": 10}
# How often each packet goes out (seconds), as the SimHub plugin does.
EVERY = {"telemetry": 0.0, "status": 0.0, "lap": 0.0, "session": 0.5, "damage": 0.1, "participants": 5.0}


def _u8(x: float) -> int:
    return max(0, min(255, int(x)))


def _u16(x: float) -> int:
    return max(0, min(65535, int(x)))


class Sf1000:
    """Builds and sends the packets. ``send`` is cheap: call it every frame."""

    def __init__(self, ip: str, port: int = PORT, sock: Any = None) -> None:
        self.addr = (ip, port)
        self.sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.frame_id = 0
        self._last: dict[str, float] = {}
        self.sent = 0
        self.error: str | None = None

    # -- packets ---------------------------------------------------------------

    def _header(self, kind: str, t: float) -> bytes:
        return HEADER.pack(2023, 23, 1, 18, 1, IDS[kind], 0, t, self.frame_id, self.frame_id, 0, 255)

    def telemetry(self, f: Frame, s: SessionInfo | None, t: float) -> bytes:
        max_rpm = (s.max_rpm if s else 0) or 8000
        # Rev lights: none until 80 % of max RPM, all of them at 97 %.
        rev = max(0.0, min(1.0, (f.rpm / max_rpm - 0.80) / 0.17)) * 100
        temps = [_u8(x) for x in (f.tyre_core_temp_c or [0, 0, 0, 0])]
        fl, fr, rl, rr = (f.tyre_pressure_psi or [0.0, 0.0, 0.0, 0.0])[:4]
        car = TELEMETRY.pack(
            _u16(f.speed_kmh), max(0.0, min(1.0, f.gas)), max(-1.0, min(1.0, f.steer / 4.0)), max(0.0, min(1.0, f.brake)),
            _u8(f.clutch * 100), max(-1, min(8, f.gear)), _u16(f.rpm), 1 if f.drs_open else 0, _u8(rev), 0,
            0, 0, 0, 0,  # brake temperatures (AC doesn't report them here)
            *temps, *temps,  # surface, inner (core for both)
            90,  # engine temperature
            rl, rr, fl, fr,  # the F1 order is rear-left, rear-right, front-left, front-right
            0, 0, 0, 0,
        )
        return self._header("telemetry", t) + car + bytes(TELEMETRY.size * (CARS - 1)) + TELEMETRY_TAIL.pack(255, 255, 0)

    def status(self, f: Frame, s: SessionInfo | None, t: float) -> bytes:
        max_rpm = (s.max_rpm if s else 0) or 8000
        tc = 0 if not f.tc else 2  # F1: 0 off, 1 medium, 2 full
        abs_ = 1 if f.abs else 0
        car = STATUS.pack(
            tc, abs_, 0, _u8(round((f.brake_bias or 0) * 100)), 1 if f.in_pit_lane else 0,
            float(f.fuel_l), float((s.max_fuel_l if s else 0) or 0), 0.0,
            _u16(max_rpm), _u16(max_rpm * 0.27), 8, 1 if f.drs_available else 0, 0,
            16, 16, 0, 0,  # compound (soft), visual, age, FIA flag (none)
            0.0, 0.0, float((f.battery or 0) * 4_000_000), _u8(f.ers_deploy or 0),
            100.0, 1.0, 0.0,  # harvested MGU-K / MGU-H: the wheel's ERS bar needs these (firmware quirk)
            0,
        )
        return self._header("status", t) + car + bytes(STATUS.size * (CARS - 1))

    def lap(self, f: Frame, s: SessionInfo | None, t: float) -> bytes:
        length = (s.track_length_m if s else 0) or 0
        pit = 2 if f.in_pit_box else 1 if f.in_pit_lane else 0
        car = LAP.pack(
            max(0, f.last_lap_ms), max(0, f.lap_time_ms), 0, 0, 0, 0, 0, 0,
            float(f.lap_progress * length), float((f.lap + f.lap_progress) * length), 0.0,
            _u8(f.position or 1), _u8(f.lap + 1), pit, 0, _u8(f.sector), 1 if f.tyres_out > 2 else 0,
            0, 0, 0, 0, 0, 1, 4, 2, 0,  # penalties.. grid 1, driver status 4 (flying), result 2 (active)
            0, 0, 0,
        )
        return self._header("lap", t) + car + bytes(LAP.size * (CARS - 1)) + LAP_TAIL.pack(255, 255)

    def session(self, f: Frame, s: SessionInfo | None, t: float) -> bytes:
        length = (s.track_length_m if s else 0) or 0
        left = f.session_time_left_s or 0
        head = SESSION_HEAD.pack(
            0, 25, 20, 0, _u16(length), 0, -1, 0, _u16(left), _u16(left), 80,
            1 if f.status == GameStatus.PAUSED else 0, 0, 0, 0, 0,
        )
        body = bytearray(SESSION_LEN)
        body[: len(head)] = head
        # From the end: ... game mode, rule set, time of day (4), session length,
        # speed units (km/h = 1) and temperature units (C = 0) for both players,
        # then three safety-car / red-flag counts.
        body[SESSION_LEN - 14] = 7  # game mode
        body[SESSION_LEN - 13] = 1  # rule set
        body[SESSION_LEN - 7] = 1  # speed in km/h, you
        body[SESSION_LEN - 5] = 1  # speed in km/h, second player
        return self._header("session", t) + bytes(body)

    def damage(self, f: Frame, s: SessionInfo | None, t: float) -> bytes:
        return self._header("damage", t) + bytes(DAMAGE.size * CARS)

    def participants(self, f: Frame, s: SessionInfo | None, t: float) -> bytes:
        return self._header("participants", t) + bytes([1]) + bytes(PARTICIPANT_LEN * CARS)

    # -- sending ---------------------------------------------------------------

    def send(self, f: Frame, s: SessionInfo | None, now: float | None = None) -> int:
        """Send whatever's due; returns how many packets went."""
        if f.status == GameStatus.OFF:
            return 0
        now = time.monotonic() if now is None else now
        self.frame_id += 1
        n = 0
        for kind, every in EVERY.items():
            if now - self._last.get(kind, -1e9) >= every:
                self._last[kind] = now
                try:
                    self.sock.sendto(getattr(self, kind)(f, s, float(f.t)), self.addr)
                    n += 1
                    self.error = None
                except OSError as e:  # wheel off, wrong IP, no Wi-Fi: keep going
                    self.error = str(e)
        self.sent += n
        return n

    def test_pattern(self, s: SessionInfo | None = None, steps: int = 40, pause_s: float = 0.05) -> None:
        """Sweep the rev lights, gears and speed so you can see the link works."""
        for i in range(steps):
            k = i / max(1, steps - 1)
            f = Frame(t=float(i), status=GameStatus.LIVE, gear=1 + int(k * 7), rpm=int(8000 * (0.75 + 0.25 * k)),
                      speed_kmh=300 * k, lap_time_ms=int(k * 90_000), last_lap_ms=88_888, lap=1)
            self._last.clear()
            self.send(f, s or SessionInfo(game="ac", car="test", track="test", max_rpm=8000, track_length_m=5000))
            time.sleep(pause_s)
