"""Turns a stream of frames into completed laps with traces."""

from __future__ import annotations

import math
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
    "batt",  # battery charge 0..1 (0 for cars without one)
    "drs",  # 0 = closed / not available, 1 = available, 2 = open
    "off",  # wheels off the track (0..4): where you went off, for the lap review
    "ffb",  # force feedback output (|AC finalFF|, 0..1): 1 = clipping
)


REWIND = "rewind"  # jumped back along the track (Time Shift, a drill retry)
TELEPORT = "teleport"  # jumped forward, or somewhere else entirely


class JumpDetector:
    """Spots the car jumping instead of driving: a teleport, a rewind (Time
    Shift, a drill retry) or a reset. Feed it live frames in order; ``step``
    says whether this frame jumped from the last one: REWIND, TELEPORT or None.

    A jump is moving further than the car's speed allows, or going backwards
    along the track faster than a car can reverse. Paused or replay frames in
    between don't count as time to cover ground (the comparison spans them).
    """

    BACK = 0.003  # lap fraction backwards in one frame (~15 m): only a rewind does that
    MAX_REWIND = 0.2  # further back than this (a fifth of a lap) is a teleport, not a Time Shift rewind
    SLACK_M = 8.0

    def __init__(self) -> None:
        self._prev: Frame | None = None

    def reset(self) -> None:
        self._prev = None

    def step(self, f: Frame) -> str | None:
        prev, self._prev = self._prev, f
        if prev is None or f.packet_id == prev.packet_id:
            return None
        back = (prev.lap_progress - f.lap_progress) % 1.0
        if self.BACK < back < 0.5:
            return REWIND if back <= self.MAX_REWIND else TELEPORT
        if f.world is None or prev.world is None:
            return None
        moved = math.dist(f.world, prev.world)
        game_dt = (f.lap_time_ms - prev.lap_time_ms) / 1000 if f.lap == prev.lap else 0.0
        dt = max(game_dt, min(max(f.t - prev.t, 0.0), 0.25))
        v = max(f.speed_kmh, prev.speed_kmh) / 3.6
        if moved <= v * dt * 1.5 + self.SLACK_M:
            return None
        return REWIND if 0.0 < back <= self.MAX_REWIND else TELEPORT


@dataclass
class _LapBuffer:
    lap_number: int
    started_at: float
    started_in_pit: bool
    first_progress: float
    first_lap_time_ms: int
    trace: dict[str, list[float]] = field(default_factory=lambda: {c: [] for c in TRACE_CHANNELS})
    sector_ms: list[int] = field(default_factory=list)
    last_sector: int = 0
    cuts: list[float] = field(default_factory=list)  # where too many wheels were off (lap progress)
    last_packet: int = -1
    last_lap_ms_at_start: int = 0
    jumped: bool = False  # teleported, or practised (drill retries): not a lap driven start to finish
    rewound: bool = False  # used a rewind after a mistake: a normal lap, but never a best
    discard: bool = False  # the leftover of a rewind back over the line: not a lap at all

    def rewind_to(self, f: Frame) -> None:
        """Time Shift took the car back: forget what it erased (samples, sector
        times and cuts past where it landed), as if the mistake never happened."""
        p = f.lap_progress
        tr = self.trace
        n = len(tr["p"])
        while n and tr["p"][n - 1] >= p:
            n -= 1
        for ch in tr.values():
            del ch[n:]
        if f.sector < self.last_sector:
            del self.sector_ms[f.sector:]
            self.last_sector = f.sector
        self.cuts = [c for c in self.cuts if c < p]
        self.rewound = True

    def add(self, f: Frame, max_tyres_out: int = 2) -> None:
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
        tr["batt"].append(round(f.battery, 3) if f.battery is not None else 0.0)
        tr["drs"].append(2 if f.drs_open else 1 if f.drs_available else 0)
        tr["off"].append(f.tyres_out)
        tr["ffb"].append(round(min(1.0, abs(f.ffb)), 3) if f.ffb is not None else 0.0)
        if f.tyres_out > max_tyres_out:
            self.cuts.append(f.lap_progress)
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
    track (AC's own cut rule is "more than two"), and it was driven from the
    line to the line: laps started in the pits or partway round, or with a
    teleport or drill practice in them, are flagged ``out_lap`` and never
    count as valid, so they can't become a best lap or a reference.

    A lap where you rewound after a mistake (Time Shift, not in a drill) is a
    normal lap flagged ``rewound``: the erased bit is dropped from it, it
    counts in your stats, but it's never a best lap, a reference or part of
    the best sectors. Set ``practising`` while a drill runs.
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
        self._jumps = JumpDetector()
        self.practising = False  # a drill is running: rewinds there are practice, not mistakes

    def feed(self, frame: Frame, session: SessionInfo | None) -> None:
        if session is None or frame.status == GameStatus.OFF:
            self._buf = None
            self._pending = None
            self._jumps.reset()
            return

        key = (session.game, session.car, session.track_key)
        if key != self._session_key:
            self._session_key = key
            self._buf = None
            self._pending = None
            self._jumps.reset()
        self._session = session

        self._maybe_finalize(frame)

        if frame.status != GameStatus.LIVE:
            return  # paused / replay: don't record, keep the buffer

        buf = self._buf
        jump = self._jumps.step(frame)
        if jump == REWIND and not self.practising:
            if buf is not None and frame.lap == buf.lap_number:
                buf.rewind_to(frame)
        elif jump and buf is not None:
            buf.jumped = True
        if buf is not None and frame.lap < buf.lap_number:
            # Session restarted, or rewound back over the line: the lap before
            # is already saved, and this bit until the line isn't a lap.
            buf = None
            if jump == REWIND:
                buf = self._new_buffer(frame, jumped=False)
                buf.discard = True

        if buf is not None and frame.lap > buf.lap_number:
            self._pending = (buf, buf.last_lap_ms_at_start, frame.t)
            buf = None
            self._maybe_finalize(frame)

        if buf is None:
            buf = self._new_buffer(frame, jumped=bool(jump))
        self._buf = buf
        buf.add(frame, self.max_tyres_out)

    def _new_buffer(self, frame: Frame, jumped: bool) -> _LapBuffer:
        return _LapBuffer(
            lap_number=frame.lap,
            started_at=self._wall(),
            started_in_pit=frame.in_pit_box or frame.in_pit_lane,
            first_progress=frame.lap_progress,
            first_lap_time_ms=frame.lap_time_ms,
            last_sector=frame.sector,
            last_lap_ms_at_start=frame.last_lap_ms,
            jumped=jumped,
        )

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
        if buf.samples < 10 or lap_ms <= 0 or buf.discard:
            return
        sectors = list(buf.sector_ms)
        if sectors:
            sectors.append(lap_ms - sum(sectors))
        # Joined partway round (e.g. the rig service started mid-lap) or from the pits.
        # The lap clock was already running when we started recording it.
        partial = buf.first_lap_time_ms > 5000
        out_lap = buf.started_in_pit or partial or buf.jumped
        lap = Lap(
            game=self._session.game,
            car=self._session.car,
            track_key=self._session.track_key,
            lap_number=buf.lap_number + 1,
            lap_time_ms=lap_ms,
            valid=(not out_lap) and not buf.cuts,
            out_lap=out_lap,
            rewound=buf.rewound and not out_lap,
            started_at=buf.started_at,
            sector_ms=sectors,
            trace=buf.trace,
        )
        self._on_lap(lap)
