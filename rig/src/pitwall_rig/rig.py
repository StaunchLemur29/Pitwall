"""The rig loop: poll the game, record laps, derive live values, emit events."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .adapters.base import GameAdapter
from .adapters.replay import Recorder
from .config import ACTIONS, Config
from .input import InputEvent
from .laps import LapRecorder
from .models import Frame, GameStatus, Lap, Mode, SessionInfo, mode_for
from .reference import ReferenceLap, downsample
from .storage import Store

log = logging.getLogger(__name__)

Event = dict[str, Any]


class Rig:
    def __init__(
        self,
        adapter: GameAdapter,
        store: Store,
        config: Config,
        emit: Callable[[Event], None] = lambda e: None,
        recorder: Recorder | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.config = config
        self.emit = emit
        self.recorder = recorder
        self._clock = clock
        self.frame: Frame | None = None
        self.session: SessionInfo | None = None
        self.mode: Mode = Mode.IDLE
        self.reference: ReferenceLap | None = None
        self.theoretical_best_ms: int | None = None
        self.delta_s: float | None = None
        self.started_at = time.time()
        self.driving_s = 0.0
        self._last_tick: float | None = None
        self.pending_bind: str | None = None
        self.laps = LapRecorder(self._on_lap, max_tyres_out=config["laps"]["max_tyres_out"])

    # -- main loop ----------------------------------------------------------

    def tick(self) -> None:
        now = self._clock()
        frame = self.adapter.poll()
        session = self.adapter.session() if frame is not None else None
        if frame is None:
            frame = Frame(t=now, status=GameStatus.OFF)

        if self._session_changed(session):
            self.session = session
            if session is not None:
                log.info("Session: %s on %s (%s)", session.car, session.track_key, session.session_type.value)
            else:
                log.info("No session (game closed or in menus)")
            self._load_reference()
            self.emit({"type": "session", "session": session.to_dict() if session else None})

        mode = mode_for(frame)
        if mode != self.mode:
            self.mode = mode
            self.emit({"type": "mode", "mode": mode.value})

        if self._last_tick is not None and mode == Mode.DRIVING:
            self.driving_s += now - self._last_tick
        self._last_tick = now

        self.frame = frame
        self.laps.max_tyres_out = self.config["laps"]["max_tyres_out"]
        self.laps.feed(frame, session)
        if self.recorder is not None and frame.status != GameStatus.OFF:
            self.recorder.add(frame, session)
        self.delta_s = (
            self.reference.delta(frame.lap_progress, frame.lap_time_ms)
            if self.reference and frame.status == GameStatus.LIVE and not frame.in_pit_box
            else None
        )

    def _session_changed(self, s: SessionInfo | None) -> bool:
        a, b = self.session, s
        if a is None or b is None:
            return a is not b
        return (a.game, a.car, a.track_key, a.session_type) != (b.game, b.car, b.track_key, b.session_type)

    # -- laps & references --------------------------------------------------

    def _load_reference(self) -> None:
        self.reference = None
        self.theoretical_best_ms = None
        s = self.session
        if s is None:
            return
        best = self.store.best_lap(s.game, s.track_key, s.car)
        if best:
            trace = self.store.trace(best["id"])
            if trace:
                self.reference = ReferenceLap(trace, best["lap_time_ms"], best["id"])
        secs = self.store.best_sectors(s.game, s.track_key, s.car)
        self.theoretical_best_ms = sum(secs) if secs else None

    def _on_lap(self, lap: Lap) -> None:
        self.store.add_lap(lap)
        new_best = lap.valid and (self.reference is None or lap.lap_time_ms < self.reference.lap_time_ms)
        if new_best:
            self.reference = ReferenceLap(lap.trace, lap.lap_time_ms, lap.id)
        s = self.session
        if s is not None:
            secs = self.store.best_sectors(s.game, s.track_key, s.car)
            self.theoretical_best_ms = sum(secs) if secs else None
        log.info(
            "Lap %d: %s%s%s",
            lap.lap_number,
            fmt_ms(lap.lap_time_ms),
            "" if lap.valid else " (invalid)",
            " — new best!" if new_best else "",
        )
        self.emit({"type": "lap", "lap": lap.summary(), "new_best": new_best})

    # -- snapshots for the dashboard ---------------------------------------

    def live(self) -> Event:
        f = self.frame
        return {
            "type": "frame",
            "frame": f.to_wire() if f else None,
            "delta_s": self.delta_s,
            "ref_lap_ms": self.reference.lap_time_ms if self.reference else None,
            "theoretical_best_ms": self.theoretical_best_ms,
            "driving_s": round(self.driving_s, 1),
        }

    def hello(self) -> Event:
        s = self.session
        return {
            "type": "hello",
            "config": self.config.data,
            "actions": ACTIONS,
            "capabilities": self.adapter.capabilities.__dict__,
            "game": self.adapter.game_id,
            "session": s.to_dict() if s else None,
            "mode": self.mode.value,
            "started_at": self.started_at,
            "recent_laps": self.recent_laps(),
        }

    def recent_laps(self, limit: int = 30) -> list[dict[str, Any]]:
        s = self.session
        if s is None:
            return []
        return self.store.laps(s.game, s.track_key, s.car, limit=limit)

    def outline(self, max_points: int = 1000) -> Event:
        s = self.session
        if s is None:
            return {"points": [], "markers": []}
        lap_id = self.store.outline_lap_id(s.game, s.track_key)
        points: list[list[float]] = []
        if lap_id is not None:
            tr = self.store.trace(lap_id) or {}
            xs, zs, ps = tr.get("x", []), tr.get("z", []), tr.get("p", [])
            k = max(1, len(xs) // max_points)
            points = [[xs[i], zs[i], ps[i]] for i in range(0, len(xs), k)]
        return {"points": points, "markers": self.store.markers(s.game, s.track_key)}

    def lap_trace(self, lap_id: int, hz: float = 20) -> dict[str, list[float]] | None:
        tr = self.store.trace(lap_id)
        return downsample(tr, hz) if tr else None

    # -- actions & bindings -------------------------------------------------

    def action(self, name: str) -> None:
        if name not in ACTIONS:
            return
        if name == "mark_corner":
            s, f = self.session, self.frame
            if s is None or f is None or f.status == GameStatus.OFF:
                return
            x, _, z = f.world if f.world else (None, None, None)
            self.store.add_marker(s.game, s.car, s.track_key, f.lap_progress, x, z)
            self.emit({"type": "markers", "markers": self.store.markers(s.game, s.track_key)})
        self.emit({"type": "action", "action": name})

    def raw_input(self, ev: InputEvent) -> None:
        """Called for every wheel press; completes a pending "press to bind"."""
        if self.pending_bind is None:
            return
        action, self.pending_bind = self.pending_bind, None
        data = dict(self.config.data)
        binds = dict(data["bindings"])
        keep = [b for b in binds.get(action, []) if b.get("type") == "key"]
        binds[action] = keep + [ev.as_binding()]
        data["bindings"] = binds
        self.config.update(data)
        self.emit({"type": "bound", "action": action, "binding": ev.as_binding()})
        self.emit({"type": "config", "config": self.config.data})


def fmt_ms(ms: int) -> str:
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"
