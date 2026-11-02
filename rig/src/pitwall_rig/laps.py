"""Turns a stream of frames into completed laps with traces."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import Frame, GameStatus, Lap, SessionInfo

#: Channels stored per sample in a lap trace.
TRACE_CHANNELS = (
    "t",  # seconds into the lap
    "p",  # lap progress 0..1
    "x",
    "y",
    "z",
    "speed",
    "gas",
    "brake",
    "steer",
    "gear",
    "rpm",
)


@dataclass
class _LapBuffer:
    lap_number: int
    started_at: float
    started_in_pit: bool
    first_progress: float
    trace: dict[str, list[float]] = field(default_factory=lambda: {c: [] for c in TRACE_CHANNELS})
    sector_ms: list[int] = field(default_factory=list)
    last_sector: int = 0
    max_tyres_out: int = 0
    last_packet: int = -1
    last_lap_ms_at_start: int = 0

    def add(self, f: Frame) -> None:
        if f.packet_id == self.last_packet:
            return
        self.last_packet = f.packet_id
        x, y, z = f.world if f.world else (0.0, 0.0, 0.0)
        tr = self.trace
        tr["t"].append(round(f.lap_time_ms / 1000.0, 3))
        tr["p"].append(round(f.lap_progress, 5))
        tr["x"].append(round(x, 2))
        tr["y"].append(round(y, 2))
        tr["z"].append(round(z, 2))
        tr["speed"].append(round(f.speed_kmh, 2))
        tr["gas"].append(round(f.gas, 3))
        tr["brake"].append(round(f.brake, 3))
        tr["steer"].append(round(f.steer, 4))
        tr["gear"].append(f.gear)
        tr["rpm"].append(f.rpm)
        self.max_tyres_out = max(self.max_tyres_out, f.tyres_out)
        if f.sector != self.last_sector:
            # crossed into a new sector: time of the previous ones so far
            self.sector_ms.append(f.lap_time_ms - sum(self.sector_ms))
            self.last_sector = f.sector

    @property
    def samples(self) -> int:
        return len(self.trace["t"])


class LapRecorder:
    """Feed it frames; it calls ``on_lap`` with each completed lap.

    A lap counts as *valid* when no more than ``max_tyres_out`` wheels left the
    track (AC's own cut rule is "more than two"), and it didn't start in the pits
    or partway round (those are flagged ``out_lap``).
    """

    def __init__(
        self,
        on_lap: Callable[[Lap], None],
        max_tyres_out: int = 2,
        wall_clock: Callable[[], float] = time.time,
        finalize_timeout_s: float = 1.0,
    ) -> None:
        self._on_lap = on_lap
        self.max_tyres_out = max_tyres_out
        self._wall = wall_clock
        self._timeout = finalize_timeout_s
        self._session_key: tuple[str, str, str] | None = None
        self._session: SessionInfo | None = None
        self._buf: _LapBuffer | None = None
        self._pending: tuple[_LapBuffer, int, float] | None = None  # buffer, prev last_lap_ms, t

    def feed(self, frame: Frame, session: SessionInfo | None) -> None:
        if session is None or frame.status == GameStatus.OFF:
            self._buf = None
            self._pending = None
            return

        key = (session.game, session.car, session.track_key)
        if key != self._session_key:
            self._session_key = key
            self._buf = None
            self._pending = None
        self._session = session

        self._maybe_finalize(frame)

        if frame.status != GameStatus.LIVE:
            return  # paused / replay: don't record, keep the buffer

        buf = self._buf
        if buf is not None and frame.lap < buf.lap_number:
            buf = None  # session restarted

        if buf is not None and frame.lap > buf.lap_number:
            self._pending = (buf, buf.last_lap_ms_at_start, frame.t)
            buf = None
            self._maybe_finalize(frame)

        if buf is None:
            buf = _LapBuffer(
                lap_number=frame.lap,
                started_at=self._wall(),
                started_in_pit=frame.in_pit_box or frame.in_pit_lane,
                first_progress=frame.lap_progress,
                last_sector=frame.sector,
                last_lap_ms_at_start=frame.last_lap_ms,
            )
            self._buf = buf
        buf.add(frame)

    def _maybe_finalize(self, frame: Frame) -> None:
        if self._pending is None or self._session is None:
            return
        buf, prev_last, t0 = self._pending
        updated = frame.last_lap_ms > 0 and frame.last_lap_ms != prev_last
        timed_out = frame.t - t0 >= self._timeout
        if not (updated or timed_out):
            return
        self._pending = None
        if updated:
            lap_ms = frame.last_lap_ms
        else:
            lap_ms = int(buf.trace["t"][-1] * 1000) if buf.samples else 0
        if buf.samples < 10 or lap_ms <= 0:
            return
        sectors = list(buf.sector_ms)
        if sectors:
            sectors.append(lap_ms - sum(sectors))
        # Joined partway round (e.g. the rig service started mid-lap) or from the pits.
        partial = 0.05 < buf.first_progress < 0.95
        out_lap = buf.started_in_pit or partial
        lap = Lap(
            game=self._session.game,
            car=self._session.car,
            track_key=self._session.track_key,
            lap_number=buf.lap_number + 1,
            lap_time_ms=lap_ms,
            valid=(not out_lap) and buf.max_tyres_out <= self.max_tyres_out,
            out_lap=out_lap,
            started_at=buf.started_at,
            sector_ms=sectors,
            trace=buf.trace,
        )
        self._on_lap(lap)
