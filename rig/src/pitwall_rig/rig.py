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
from .analysis import analyse_lap, corner_mastery, width_advice
from .storage import Store
from .tracks.live import Drill, TrackState
from .tracks.loader import from_lap_trace
from .tracks.model import TrackModel

log = logging.getLogger(__name__)

Event = dict[str, Any]


def _locked(fn):  # type: ignore[no-untyped-def]
    """Rig state is touched by the telemetry thread and the web server: one at a time."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):  # type: ignore[no-untyped-def]
        with self.lock:
            return fn(self, *a, **kw)

    return wrapper


class Rig:
    def __init__(
        self,
        adapter: GameAdapter,
        store: Store,
        config: Config,
        emit: Callable[[Event], None] = lambda e: None,
        recorder: Recorder | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        import threading

        self.lock = threading.RLock()
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
        self.on_open_analysis: Callable[[], object] = lambda: None
        self.on_close_window: Callable[[str], object] = lambda which: None
        self.on_minimize_window: Callable[[str], object] = lambda which: None
        self.on_shutdown: Callable[[], object] = lambda: None
        from .input import KeyHolder

        self.keys = KeyHolder()
        self._retry: dict[str, float] | None = None
        # rates for the lag meter: rig ticks/s and new game packets/s
        self._rate_t0 = time.perf_counter()
        self._ticks = 0
        self._packets = 0
        self._last_packet = -1
        self.tick_hz = 0.0
        self.game_hz = 0.0
        from collections import deque

        self.tick_ms: deque[float] = deque(maxlen=3000)  # how long each tick took
        self.track: TrackState | None = None
        self.track_live: dict[str, Any] | None = None
        self.laps = LapRecorder(self._on_lap, max_tyres_out=config["laps"]["max_tyres_out"])

    # -- main loop ----------------------------------------------------------

    def tick(self) -> None:
        t_start = time.perf_counter()
        try:
            self._tick()
        finally:
            self.tick_ms.append((time.perf_counter() - t_start) * 1000)

    def _tick(self) -> None:
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
            self._load_track()

        mode = mode_for(frame)
        if mode != self.mode:
            self.mode = mode
            self.emit({"type": "mode", "mode": mode.value})

        if self._last_tick is not None and mode == Mode.DRIVING:
            self.driving_s += now - self._last_tick
        self._last_tick = now

        self._ticks += 1
        if frame.packet_id != self._last_packet:
            self._packets += 1
            self._last_packet = frame.packet_id
        span = now - self._rate_t0
        if span >= 1.0:
            self.tick_hz, self.game_hz = self._ticks / span, self._packets / span
            self._rate_t0, self._ticks, self._packets = now, 0, 0

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
        if self._retry is not None:
            self._retry_step(frame, now)
        if self.track is not None:
            self.track.max_tyres_out = self.config["laps"]["max_tyres_out"]
            self.track_live = self.track.update(frame)
            attempt = (self.track_live or {}).pop("attempt", None)
            if attempt is not None:
                self.emit({"type": "attempt", "attempt": attempt})
        else:
            self.track_live = None

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
        if self.track is None or (self.track.model.source == "laps" and new_best):
            self._load_track()  # a first (or better) lap lets us draw a learnt map
        elif self.track is not None:
            if new_best:
                self.track.set_reference(lap.trace)
            if lap.valid and lap.id is not None:
                self._analyse(lap.id, lap.trace)
            self._emit_corners(lap.id)
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

    # -- track ----------------------------------------------------------------

    def _load_track(self) -> None:
        s = self.session
        self.track = None
        if s is None:
            self.emit({"type": "track", "track": None})
            return
        model: TrackModel | None = None
        try:
            model = self.adapter.track_model(s)
        except Exception:  # noqa: BLE001 - a bad mod track must not stop telemetry
            log.exception("Couldn't load the track layout for %s", s.track_key)
        if model is None:
            lap_id = self.store.outline_lap_id(s.game, s.track_key)
            trace = self.store.trace(lap_id) if lap_id is not None else None
            if trace:
                model = from_lap_trace(s.track_key, trace, s.track_length_m)
        if model is None:
            self.emit({"type": "track", "track": None})
            return
        self.track = TrackState(model, self.config["laps"]["max_tyres_out"])
        self.track.on_attempt = self._save_attempt
        if self.reference is not None and self.reference.lap_id is not None:
            self.track.set_reference(self.store.trace(self.reference.lap_id))
        for lap_id in self.store.valid_lap_ids(s.game, s.track_key, s.car):
            if self.store.lap_corners(lap_id, self._model_sig()) is None:
                tr = self.store.trace(lap_id)
                if tr:
                    self._analyse(lap_id, tr)
        self.track.mastery = self._mastery()
        self.emit({"type": "track", "track": model.geometry()})
        self._emit_corners(None)

    def _model_sig(self) -> str:
        m = self.track.model if self.track else None
        if m is None:
            return ""
        return f"v1:{m.source}:{len(m.corners)}:{round(m.length_m)}"

    def _analyse(self, lap_id: int, trace: dict[str, list[float]]) -> None:
        if self.track is None:
            return
        self.store.set_lap_corners(lap_id, self._model_sig(), analyse_lap(trace, self.track.model))

    def _mastery(self) -> dict[int, dict[str, Any]]:
        s = self.session
        if s is None or self.track is None:
            return {}
        history = []
        for lap_id in self.store.valid_lap_ids(s.game, s.track_key, s.car, limit=30):
            data = self.store.lap_corners(lap_id, self._model_sig())
            if data:
                history.append(data)
        return corner_mastery(history)

    @_locked
    def corner_report(self, lap_id: int | None = None) -> Event:
        """Mastery per corner plus one lap's corner-by-corner numbers."""
        if self.track is None:
            return {"mastery": [], "lap": None, "lap_id": None, "reference": [], "chapters": [], "practice": []}
        s = self.session
        if lap_id is None and s is not None:
            ids = self.store.valid_lap_ids(s.game, s.track_key, s.car, limit=1)
            lap_id = ids[0] if ids else None
        lap = self.store.lap_corners(lap_id, self._model_sig()) if lap_id is not None else None
        if lap:
            m = self.track.model
            if not self.track.mastery:
                self.track.mastery = self._mastery()
            for i, data in enumerate(lap):
                c = m.corners[i] if i < len(m.corners) else None
                if c is None:
                    continue
                nxt = m.corners[(i + 1) % len(m.corners)]
                gap = ((nxt.entry - c.exit) % 1.0) * m.length_m
                data["advice"] = width_advice(c, data, gap)
                # Time lost against your best ever through this corner (any lap).
                best = self.track.mastery.get(c.number, {}).get("best_s")
                data["loss_s"] = round(data["time_s"] - best, 3) if best is not None else None
        chapters = self._chapter_times(lap_id)
        practice = self._practice_times(lap_id)
        return {
            "chapters": chapters,
            "practice": practice,
            "mastery": list(self.track.mastery.values()),
            "lap_id": lap_id,
            "lap": lap,
            "reference": list(self.track.ref_corners.values()),
            "reference_lap_id": self.reference.lap_id if self.reference else None,
        }

    def _chapter_times(self, lap_id: int | None) -> list[dict[str, Any]]:
        """Each pack chapter with this lap's time through it and your reference lap's."""
        if self.track is None or not self.track.model.chapters:
            return []
        from .analysis import LapView

        def span(view: LapView | None, a: float, b: float) -> float | None:
            if not view:
                return None
            if b > a:
                return round(view.time_at(b) - view.time_at(a), 3)
            return None  # runs over the line: needs two laps

        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        view = LapView(lap_trace) if lap_trace else None
        ref = self.track.ref_view
        out = []
        for ch in self.track.model.chapters:
            d = ch.to_dict()
            d["time_s"] = span(view, ch.start, ch.end)
            d["ref_s"] = span(ref, ch.start, ch.end)
            out.append(d)
        return out

    def _practice_times(self, lap_id: int | None) -> list[dict[str, Any]]:
        """Each practice section with this lap's time, your best lap's, and your
        best clean drill attempt."""
        if self.track is None:
            return []
        from .analysis import LapView

        s = self.session
        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        view = LapView(lap_trace) if lap_trace else None
        ref = self.track.ref_view

        def span(v: LapView | None, a: float, b: float) -> float | None:
            return round(v.time_at(b) - v.time_at(a), 3) if v and b > a else None

        out = []
        for ps in self.track.model.practice:
            d = ps.to_dict()
            d["time_s"] = span(view, ps.start, ps.end)
            d["ref_s"] = span(ref, ps.start, ps.end)
            best = self.store.best_section_ms(s.game, s.car, s.track_key, ps.start, ps.end) if s else None
            d["drill_best_s"] = best / 1000 if best else None
            out.append(d)
        return out

    @_locked
    def drill_section(self, number: int) -> bool:
        if self.track is None:
            return False
        ps = next((p for p in self.track.model.practice if p.number == number), None)
        return ps is not None and self.start_drill(ps.start, ps.end, ps.name)

    @_locked
    def drill_chapter(self, number: int) -> bool:
        if self.track is None:
            return False
        ch = next((c for c in self.track.model.chapters if c.number == number), None)
        return ch is not None and self.start_drill(ch.start, ch.end, ch.name)

    def _emit_corners(self, lap_id: int | None) -> None:
        if self.track is not None:
            self.track.mastery = self._mastery()
        self.emit({"type": "corners", **self.corner_report(lap_id)})

    # -- drills -----------------------------------------------------------------

    @_locked
    def start_drill(self, start_p: float, end_p: float, name: str, corner: int | None = None) -> bool:
        s = self.session
        if self.track is None or s is None:
            return False
        drill = Drill(name=name, start_p=start_p % 1.0, end_p=end_p % 1.0, corner=corner)
        best = self.store.best_section_ms(s.game, s.car, s.track_key, drill.start_p, drill.end_p)
        self.track.start_drill(drill, best)
        self.emit({"type": "drill", "drill": self.track.drill.to_wire() if self.track.drill else None})
        return True

    @_locked
    def drill_corner(self, number: int) -> bool:
        if self.track is None:
            return False
        m = self.track.model
        c = next((c for c in m.corners if c.number == number), None)
        if c is None:
            return False
        before, after = 150.0 / m.length_m, 60.0 / m.length_m
        return self.start_drill(c.entry - before, c.exit + after, c.label, c.number)

    # -- automatic retry (hold Time Shift until we're back before the section) --

    RETRY_BEHIND_M = (40.0, 600.0)  # stop rewinding once this far before the start

    @_locked
    def start_retry(self) -> bool:
        if self.track is None or self.track.drill is None or self.frame is None:
            return False
        if not self.keys.down(self.config["games"]["ac"]["rewind_key"]):
            return False
        self._retry = {"t0": self._clock(), "p0": self.frame.lap_progress, "moved": 0.0}
        self.emit({"type": "retry", "state": "rewinding"})
        return True

    def _retry_step(self, f: Frame, now: float) -> None:
        r = self._retry
        assert r is not None and self.track is not None
        drill = self.track.drill
        length = self.track.model.length_m
        done = None
        if drill is None:
            done = "stopped"
        else:
            behind_m = ((drill.drill.start_p - f.lap_progress) % 1.0) * length
            back_m = ((r["p0"] - f.lap_progress) % 1.0) * length
            if back_m < length / 2:
                r["moved"] = max(r["moved"], back_m)
            if self.RETRY_BEHIND_M[0] <= behind_m <= self.RETRY_BEHIND_M[1] and r["moved"] > 1:
                done = "ready"
            elif now - r["t0"] > 1.5 and r["moved"] < 1:
                done = "no_rewind"  # Time Shift didn't react: key not bound?
            elif now - r["t0"] > 20:
                done = "timeout"
        if done:
            self.keys.up()
            self._retry = None
            self.emit({"type": "retry", "state": done})

    @_locked
    def stop_drill(self) -> None:
        if self.track is not None:
            self.track.stop_drill()
        self.emit({"type": "drill", "drill": None})

    def _save_attempt(self, a: dict[str, Any]) -> None:
        s = self.session
        if s is not None:
            self.store.add_section_attempt(
                s.game, s.car, s.track_key, a["start_p"], a["end_p"], a["time_ms"], a["clean"]
            )

    # -- snapshots for the dashboard ---------------------------------------

    def live(self) -> Event:
        f = self.frame
        # How old the position is right now: lets the dashboard predict the car
        # from the moment the game actually moved it.
        pos_age = None
        if f is not None and f.world_t is not None:
            pos_age = round(max(0.0, min(0.5, self._clock() - f.world_t)) * 1000, 2)
        return {
            "type": "frame",
            "ts": time.time(),
            "tick_hz": round(self.tick_hz, 1),
            "game_hz": round(self.game_hz, 1),
            "frame": f.to_wire() if f else None,
            "pos_age_ms": pos_age,
            "delta_s": self.delta_s,
            "ref_lap_ms": self.reference.lap_time_ms if self.reference else None,
            "theoretical_best_ms": self.theoretical_best_ms,
            "driving_s": round(self.driving_s, 1),
            "track": self.track_live,
        }

    @_locked
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
            "track": self.track.model.geometry() if self.track else None,
            "corners": self.corner_report() if self.track else None,
            "drill": self.track.drill.to_wire() if self.track and self.track.drill else None,
        }

    def recent_laps(self, limit: int = 30) -> list[dict[str, Any]]:
        s = self.session
        if s is None:
            return []
        return self.store.laps(s.game, s.track_key, s.car, limit=limit)

    @_locked
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

    @_locked
    def action(self, name: str, pressed: bool = True) -> None:
        if name not in ACTIONS:
            return
        if name == "rewind":
            # During a drill, one press rewinds to just before the section.
            if self.track is not None and self.track.drill is not None:
                if pressed and self._retry is None:
                    self.start_retry()
                return
            # Otherwise Time Shift rewinds for as long as its key is held:
            # mirror the wheel button.
            if pressed:
                self.keys.down(self.config["games"]["ac"]["rewind_key"])
            elif self._retry is None:
                self.keys.up()
            return
        if not pressed:
            return
        if name == "mark_corner":
            s, f = self.session, self.frame
            if s is None or f is None or f.status == GameStatus.OFF:
                return
            x, _, z = f.world if f.world else (None, None, None)
            self.store.add_marker(s.game, s.car, s.track_key, f.lap_progress, x, z)
            self.emit({"type": "markers", "markers": self.store.markers(s.game, s.track_key)})
        elif name == "drill_here":
            corner = (self.track_live or {}).get("corner")
            if corner and self.track is not None:
                ps = next((p for p in self.track.model.practice if corner["number"] in p.corners), None)
                if ps is not None:
                    self.drill_section(ps.number)
                else:
                    self.drill_corner(corner["number"])
        elif name == "stop_drill":
            self.stop_drill()
        elif name == "open_analysis":
            self.on_open_analysis()
        elif name == "retry_drill":
            self.start_retry()
        self.emit({"type": "action", "action": name})

    @_locked
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
