"""Record any adapter's output to a file, and replay it later.

File format (``.pwrec``): gzip'd JSON lines. Line 1 is a header
``{"format": "pitwall-rec", "version": 1, "game": ..., "capabilities": {...}}``.
Each following line is either ``{"session": {...}}`` (whenever session info
changes) or ``{"frame": {...}}`` with ``t`` relative to the start of recording.
"""

from __future__ import annotations

import gzip
import json
import time
import zlib
from collections.abc import Callable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import IO, Any

from ..models import Capabilities, Frame, GameStatus, SessionInfo, SessionType
from .base import GameAdapter

FORMAT = "pitwall-rec"
VERSION = 1


class Recorder:
    """Writes a recording, flushing to disk every second.

    The flush matters: if the window is closed instead of stopped with Ctrl+C,
    everything up to the last flush is still readable.
    """

    def __init__(
        self,
        path: Path | str,
        game: str,
        capabilities: Capabilities,
        flush_every_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._f = gzip.open(path, "wb")
        self._clock = clock
        self._flush_every = flush_every_s
        self._flushed_at = clock()
        self._t0: float | None = None
        self._last_session: dict[str, Any] | None = None
        self._write(
            {"format": FORMAT, "version": VERSION, "game": game, "capabilities": asdict(capabilities)}
        )
        self.flush()

    def _write(self, obj: dict[str, Any]) -> None:
        self._f.write((json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8"))

    def flush(self) -> None:
        self._f.flush(zlib.Z_SYNC_FLUSH)
        self._flushed_at = self._clock()

    def add(self, frame: Frame, session: SessionInfo | None) -> None:
        if self._t0 is None:
            self._t0 = frame.t
        if session is not None:
            s = session.to_dict()
            s.pop("track_key", None)
            if s != self._last_session:
                self._last_session = s
                self._write({"session": s})
        d = frame.to_wire()
        d["t"] = round(frame.t - self._t0, 4)
        self._write({"frame": d})
        if self._clock() - self._flushed_at >= self._flush_every:
            self.flush()

    def close(self) -> None:
        if not self._f.closed:
            self._f.close()


def _lines(f: IO[str]) -> Iterator[dict[str, Any]]:
    """JSON lines, stopping quietly at a cut-off end (recording not closed cleanly)."""
    try:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                return
    except (EOFError, gzip.BadGzipFile, zlib.error):
        return


def _frame_from(d: dict[str, Any], t: float) -> Frame:
    d = dict(d)
    d["t"] = t
    d["status"] = GameStatus(d["status"])
    if d.get("world") is not None:
        d["world"] = tuple(d["world"])
    known = Frame.__dataclass_fields__
    return Frame(**{k: v for k, v in d.items() if k in known})


def _session_from(d: dict[str, Any]) -> SessionInfo:
    d = dict(d)
    d["session_type"] = SessionType(d.get("session_type", "unknown"))
    known = SessionInfo.__dataclass_fields__
    return SessionInfo(**{k: v for k, v in d.items() if k in known})


class ReplayAdapter(GameAdapter):
    """Plays a recording back in (scaled) real time, looping at the end."""

    def __init__(
        self,
        path: Path | str,
        clock: Callable[[], float] = time.monotonic,
        time_scale: float = 1.0,
        loop: bool = True,
    ) -> None:
        self._clock = clock
        self._scale = time_scale
        self._loop = loop
        self._events: list[tuple[float, Frame | None, SessionInfo | None]] = []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            header = json.loads(f.readline())
            if header.get("format") != FORMAT:
                raise ValueError(f"{path} is not a Pitwall recording")
            self.game_id = header.get("game", "replay")
            caps = header.get("capabilities") or {}
            self.capabilities = Capabilities(
                **{k: v for k, v in caps.items() if k in Capabilities.__dataclass_fields__}
            )
            current_session: SessionInfo | None = None
            for obj in _lines(f):
                if "session" in obj:
                    current_session = _session_from(obj["session"])
                elif "frame" in obj:
                    t = float(obj["frame"]["t"])
                    self._events.append((t, _frame_from(obj["frame"], t), current_session))
        if not self._events:
            raise ValueError(f"{path} contains no frames")
        self._duration = self._events[-1][0]
        self._start: float | None = None
        self._i = 0
        self._session: SessionInfo | None = None
        self._loops = 0

    def poll(self) -> Frame | None:
        now = self._clock()
        if self._start is None:
            self._start = now
        elapsed = (now - self._start) * self._scale
        if elapsed > self._duration:
            if not self._loop:
                return Frame(t=now, status=GameStatus.OFF)
            self._start = now
            self._i = 0
            self._loops += 1
            elapsed = 0.0
        while self._i + 1 < len(self._events) and self._events[self._i + 1][0] <= elapsed:
            self._i += 1
        _, frame, session = self._events[self._i]
        self._session = session
        assert frame is not None
        out = Frame(**{**frame.__dict__, "t": now})
        # Keep packet ids unique across loops so the lap recorder doesn't dedupe them.
        out.packet_id = frame.packet_id + self._loops * 10_000_000
        return out

    def session(self) -> SessionInfo | None:
        return self._session
