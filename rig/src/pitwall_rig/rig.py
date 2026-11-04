"""The rig loop: poll the game, record laps, derive live values, emit events."""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections.abc import Callable
from typing import Any

from .adapters.base import GameAdapter
from .adapters.replay import Recorder
from .config import ACTIONS, Config
from . import car_profile
from .csp import CspLink
from .input import InputEvent
from .laps import LapRecorder
from .models import Frame, GameStatus, Lap, Mode, SessionInfo, mode_for
from .reference import ReferenceLap, downsample
from .analysis import (
    LapView,
    analyse_lap,
    analyse_systems,
    compare_notes,
    corner_mastery,
    lap_review,
    line_vs_optimal,
    time_to_beat,
    width_advice,
)
from .optimal_run import lap_time, learn_grip, simulate
from .storage import Store
from .tracks.live import Drill, TrackState
from .tracks.loader import from_lap_trace
from .tracks.model import TrackModel

log = logging.getLogger(__name__)

Event = dict[str, Any]


class AnalysisCtx:
    """Everything the analysis needs for one car on one track: the live session,
    or any car + track you've driven before."""

    def __init__(self, game: str, car: str, track_key: str, track: TrackState, ref_lap_id: int | None, live: bool):
        self.game, self.car, self.track_key = game, car, track_key
        self.track = track
        self.ref_lap_id = ref_lap_id
        self.live = live
        self.lap_count = -1  # cache check for past combos


# The optimal run learns the car's grip from this many of your fastest laps.
OPT_LAPS = 8
# What each corner row carries about the optimal run (also uploaded to the hub).
TTB_LAPS = 10  # the time to beat starts from your usual over this many recent clean laps
TTB_PAST_BEST = 0.003  # the lap's time to beat asks at most 0.3 % beyond your best lap
OPT_KEYS = ("time_s", "brake_m", "entry_kmh", "peak_brake", "min_speed_kmh", "throttle_m", "exit_kmh")


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
        self.lock = threading.RLock()
        self.adapter = adapter
        self.store = store
        self.config = config
        self.emit = emit
        self.recorder = recorder
        self._clock = clock
        self.frame: Frame | None = None
        self.session: SessionInfo | None = None
        self._ctx_cache: dict[tuple[str, str, str], AnalysisCtx] = {}
        self._opt_runs: dict[tuple[str, str, str], dict[str, Any]] = {}  # optimal run per car + track
        self._ttb: dict[tuple[str, str, str], dict[str, Any]] = {}  # time to beat per car + track (cached)
        self.time_to_beat_ms: int | None = None  # the live car + track's lap time to beat
        self._cue_mode: str | None = None  # the brake-cue setting last applied
        self._opt_busy: set[tuple[str, str, str]] = set()
        self._ac_tracks = None  # track loader for past AC tracks when another adapter is running
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
        self._retry: dict[str, Any] | None = None
        self.csp = CspLink(clock)  # the in-game CSP app, when it's running
        self.car_profile: dict[str, Any] | None = None  # which systems the current car has
        self.on_lap_saved: Callable[[], None] = lambda: None  # e.g. wake the cloud sync
        # (game, car, track_key) of a session that just ended, e.g. to write its debrief
        self.on_session_end: Callable[[str, str, str], None] = lambda g, c, t: None
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
        if self.track is not None and self.config["coach"]["brake_cue"] != self._cue_mode:
            with self.lock:
                self._apply_target()  # the setting changed
        now = self._clock()
        frame = self.adapter.poll()
        session = self.adapter.session() if frame is not None else None
        if frame is None:
            frame = Frame(t=now, status=GameStatus.OFF)

        if self._session_changed(session):
            old = self.session
            if old is not None:
                try:
                    self.on_session_end(old.game, old.car, old.track_key)
                except Exception:  # noqa: BLE001 - never let this stop telemetry
                    log.exception("Session-end hook failed")
            self.session = session
            self._load_car_profile()
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
        if self.car_profile is not None and frame.status == GameStatus.LIVE and car_profile.note_frame(self.car_profile, frame):
            self._save_car_profile()
        self.laps.max_tyres_out = self.config["laps"]["max_tyres_out"]
        self.laps.practising = self.track is not None and self.track.drill is not None
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
        self.on_lap_saved()
        new_best = lap.valid and not lap.rewound and (
            self.reference is None or lap.lap_time_ms < self.reference.lap_time_ms)
        if new_best:
            self.reference = ReferenceLap(lap.trace, lap.lap_time_ms, lap.id)
        if self.track is None or (self.track.model.source == "laps" and new_best):
            self._load_track()  # a first (or better) lap lets us draw a learnt map
        elif self.track is not None:
            if new_best:
                self.track.set_reference(lap.trace)
                self.csp.touch()
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
        self._apply_target(touch=False)
        self.csp.touch()
        self.emit({"type": "track", "track": model.geometry(compute_optimal=False)})
        self._emit_corners(None)
        if not model.optimal_ready():
            # A few seconds on a long track: work it out off the telemetry thread,
            # then send the map (and the corner tips that use it) again.
            threading.Thread(target=self._optimal_line, args=(model,), daemon=True, name="optimal-line").start()

    def _optimal_line(self, model: TrackModel) -> None:
        try:
            model.optimal()
        except Exception:  # noqa: BLE001 - the analysis works without it
            log.exception("Couldn't work out the optimal line for %s", model.track_key)
            return
        with self.lock:
            if self.track is not None and self.track.model is model:
                self.emit({"type": "track", "track": model.geometry()})
                self._emit_corners(None)

    def _model_sig(self, track: TrackState | None = None) -> str:
        track = track or self.track
        m = track.model if track else None
        if m is None:
            return ""
        return f"v4:{m.source}:{len(m.corners)}:{round(m.length_m)}"

    def _analyse(self, lap_id: int, trace: dict[str, list[float]], track: TrackState | None = None) -> None:
        track = track or self.track
        if track is None:
            return
        self.store.set_lap_corners(lap_id, self._model_sig(track), analyse_lap(trace, track.model))

    def _mastery(self, ctx: AnalysisCtx | None = None) -> dict[int, dict[str, Any]]:
        ctx = ctx or self._live_ctx()
        if ctx is None:
            return {}
        history = []
        for lap_id in self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=30):
            data = self.store.lap_corners(lap_id, self._model_sig(ctx.track))
            if data:
                history.append(data)
        return corner_mastery(history)

    # -- analysis for any car + track ----------------------------------------

    def _live_ctx(self) -> AnalysisCtx | None:
        s = self.session
        if s is None or self.track is None:
            return None
        ref = self.reference.lap_id if self.reference else None
        return AnalysisCtx(s.game, s.car, s.track_key, self.track, ref, live=True)

    def _is_live(self, game: str, car: str, track_key: str) -> bool:
        s = self.session
        return s is not None and self.track is not None and (s.game, s.car, s.track_key) == (game, car, track_key)

    def _load_model(self, game: str, car: str, track_key: str) -> TrackModel | None:
        """A track layout without a live session: from the game's files when we
        can read them, else drawn from a lap you drove there. (No lock needed.)"""
        track, _, config = track_key.partition("@")
        si = SessionInfo(game=game, car=car, track=track, track_config=config)
        model = None
        try:
            if game == self.adapter.game_id:
                model = self.adapter.track_model(si)
            elif game == "ac":
                if self._ac_tracks is None:
                    from .tracks.loader import TrackLoader

                    self._ac_tracks = TrackLoader(self.config["games"]["ac"]["install_dir"])
                model = self._ac_tracks.load(si)
        except Exception:  # noqa: BLE001
            log.exception("Couldn't load the track layout for %s", track_key)
        if model is None:
            lap_id = self.store.outline_lap_id(game, track_key)
            trace = self.store.trace(lap_id) if lap_id is not None else None
            if trace:
                model = from_lap_trace(track_key, trace, 0.0)
        if model is not None:
            try:
                model.optimal()  # outside the lock too: seconds on a long track, once
            except Exception:  # noqa: BLE001 - the analysis works without it
                log.exception("Couldn't work out the optimal line for %s", track_key)
        return model

    def analysis_ctx(self, game: str | None = None, car: str | None = None, track_key: str | None = None,
                     lap_id: int | None = None) -> AnalysisCtx | None:
        """The live session by default; another car + track if asked (directly or via a lap)."""
        if lap_id is not None and game is None:
            info = self.store.lap(lap_id)
            if info:
                game, car, track_key = info["game"], info["car"], info["track_key"]
        with self.lock:
            if game is None or car is None or track_key is None or self._is_live(game, car, track_key):
                return self._live_ctx()
            key = (game, car, track_key)
            ctx = self._ctx_cache.get(key)
            count = len(self.store.valid_lap_ids(game, track_key, car, limit=10000))
            if ctx is not None and ctx.lap_count == count:
                return ctx
        model = self._load_model(game, car, track_key)  # file reading: outside the lock
        if model is None:
            return None
        with self.lock:
            ts = TrackState(model, self.config["laps"]["max_tyres_out"])
            best = self.store.best_lap(game, track_key, car)
            if best:
                ts.set_reference(self.store.trace(best["id"]))
            for lid in self.store.valid_lap_ids(game, track_key, car):
                if self.store.lap_corners(lid, self._model_sig(ts)) is None:
                    tr = self.store.trace(lid)
                    if tr:
                        self._analyse(lid, tr, ts)
            ctx = AnalysisCtx(game, car, track_key, ts, best["id"] if best else None, live=False)
            ts.mastery = self._mastery(ctx)
            ctx.lap_count = count
            self._ctx_cache[key] = ctx
            return ctx

    def cloud_extras(self, lap_id: int) -> dict[str, Any] | None:
        """What the hub can't work out by itself: each corner with its track-width
        advice, battery & DRS on the lap, and the lap's good and bad. (Comparisons with other laps the hub
        does itself, against whichever lap you pick.)"""
        rep = self.corner_report(lap_id)
        if not rep.get("lap"):
            return None
        corners = [{k: v for k, v in c.items() if k not in ("vs_s", "notes")} for c in rep["lap"]]
        tb = rep.get("time_to_beat")
        if tb:  # as it stands after this lap, with the practice sections' targets
            tb = {**tb, "sections": [{"number": ps["number"], "to_beat_s": ps.get("to_beat_s")}
                                     for ps in rep.get("practice", [])]}
        return {"corners": corners, "systems": rep.get("systems"), "time_to_beat": tb,
                "review": rep.get("review")}

    SESSION_GAP_S = 3600  # laps more than an hour apart belong to different sessions

    def session_summary(self, game: str, car: str, track_key: str) -> dict[str, Any] | None:
        """The latest session on this car + track, condensed for the AI debrief.
        None when it has too few clean laps to be worth one."""
        from .debrief import MIN_CLEAN_LAPS

        laps = sorted(self.store.laps(game, track_key, car, limit=500), key=lambda l: l["started_at"])
        if not laps:
            return None
        sessions: list[list[dict[str, Any]]] = []
        for lap in laps:
            if sessions and lap["started_at"] - sessions[-1][-1]["started_at"] <= self.SESSION_GAP_S:
                sessions[-1].append(lap)
            else:
                sessions.append([lap])
        sess = sessions[-1]
        clean = [l for l in sess if l["valid"]]
        if len(clean) < MIN_CLEAN_LAPS:
            return None
        start = sess[0]["started_at"]
        # A lap with a rewind in it is never a best (falls back to one if that's all there is).
        best = min([l for l in clean if not l.get("rewound")] or clean, key=lambda l: l["lap_time_ms"])
        before = [l["lap_time_ms"] for l in laps if l["valid"] and not l.get("rewound") and l["started_at"] < start]
        times = sorted(l["lap_time_ms"] for l in clean)
        mid = len(times) // 2
        median = times[mid] if len(times) % 2 else (times[mid - 1] + times[mid]) / 2
        mean = sum(times) / len(times)
        spread = (sum((t - mean) ** 2 for t in times) / len(times)) ** 0.5

        rep = self.corner_report(best["id"], game=game, car=car, track_key=track_key)
        ctx = self.analysis_ctx(game, car, track_key)
        model_corners = {c.number: c for c in ctx.track.model.corners} if ctx else {}
        mastery = {m["corner"]: m for m in rep.get("mastery", [])}
        corners = []
        for c in rep.get("lap") or []:
            mc = model_corners.get(c["corner"])
            m = mastery.get(c["corner"], {})
            corners.append({
                "corner": mc.label if mc else f"Corner {c['corner']}",
                "type": f"{mc.direction}{mc.grade} (1 = tightest, 6 = flat)" if mc else None,
                "time_s": c["time_s"],
                "vs_comparison_s": c.get("vs_s"),
                "differences": (c.get("notes") or [])[:3],
                "lost_vs_best_ever_here_s": c.get("loss_s"),
                "consistency": {"grade": m.get("grade"), "spread_s": m.get("spread_s"), "laps": m.get("laps")},
                "track_width_advice": (c.get("advice") or [])[:1],
                "slowest_kmh": c.get("min_speed_kmh"),
                "gear": c.get("apex_gear"),
                "brake_m_before_apex": c.get("brake_m"),
            })
        return {
            "car": car,
            "track": track_key,
            "session": {
                "start": start,
                "laps": [{"lap": l["lap_number"], "time": fmt_ms(l["lap_time_ms"]), "clean": l["valid"],
                          "out_lap": l["out_lap"], "rewound": bool(l.get("rewound"))} for l in sess],
                "clean_laps": len(clean),
                "best": fmt_ms(best["lap_time_ms"]),
                "typical": fmt_ms(int(median)),
                "spread_s": round(spread / 1000, 2),
            },
            "personal_best_before_session": fmt_ms(min(before)) if before else None,
            "new_personal_best": not before or best["lap_time_ms"] < min(before),
            "best_sectors_combined": fmt_ms(rep["theoretical_best_ms"]) if rep.get("theoretical_best_ms") else None,
            "best_lap_compared_with": rep.get("compare_label"),
            "corners_on_best_lap": corners,
            "practice_sections": [
                {"name": ps["name"], "this_lap_s": ps.get("time_s"), "best_lap_s": ps.get("ref_s"),
                 "best_drill_run_s": ps.get("drill_best_s")}
                for ps in rep.get("practice", [])
            ],
            "battery_and_drs": (rep.get("systems") or {}).get("notes", []),
            "car_has": rep.get("car_systems", []),
            # Realistic stretch targets (your usual, part of the way to your best or the optimal run).
            "time_to_beat": _summary_targets(rep, model_corners),
        }

    def combos(self) -> list[dict[str, Any]]:
        """Every car + track you've driven, most recent first."""
        out = self.store.combos()
        s = self.session
        for c in out:
            c["live"] = s is not None and (s.game, s.car, s.track_key) == (c["game"], c["car"], c["track_key"])
        return out

    def track_geometry(self, game: str | None, car: str | None, track_key: str | None) -> dict[str, Any] | None:
        ctx = self.analysis_ctx(game, car, track_key)
        return ctx.track.model.geometry() if ctx else None

    def corner_report(self, lap_id: int | None = None, compare_id: int | None = None,
                      game: str | None = None, car: str | None = None, track_key: str | None = None) -> Event:
        """Mastery per corner plus one lap's corner-by-corner numbers, compared
        with another lap (your best by default; your next best when looking at
        the best lap itself). The live session's car + track unless another is asked for."""
        ctx = self.analysis_ctx(game, car, track_key, lap_id)
        if ctx is not None and not ctx.live:
            self._optimal_run(ctx, wait=True)  # outside the lock: reads a few laps
        with self.lock:
            return self._corner_report(ctx, lap_id, compare_id)

    def _corner_report(self, ctx: AnalysisCtx | None, lap_id: int | None, compare_id: int | None) -> Event:
        if ctx is None:
            return {"mastery": [], "lap": None, "lap_id": None, "reference": [], "chapters": [], "practice": [],
                    "compare": None, "compare_lap_id": None, "compare_label": None, "live": False,
                    "game": None, "car": None, "track_key": None, "theoretical_best_ms": None}
        track = ctx.track
        sig = self._model_sig(track)
        if lap_id is None:
            ids = self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=1)
            lap_id = ids[0] if ids else None
        lap = self.store.lap_corners(lap_id, sig) if lap_id is not None else None
        if lap is None and lap_id is not None:
            tr = self.store.trace(lap_id)  # e.g. an invalid lap picked by hand
            if tr:
                self._analyse(lap_id, tr, track)
                lap = self.store.lap_corners(lap_id, sig)
        if lap:
            m = track.model
            if not track.mastery:
                track.mastery = self._mastery(ctx)
            for i, data in enumerate(lap):
                c = m.corners[i] if i < len(m.corners) else None
                if c is None:
                    continue
                nxt = m.corners[(i + 1) % len(m.corners)]
                gap = ((nxt.entry - c.exit) % 1.0) * m.length_m
                line = line_vs_optimal(c, data, m)
                if line:
                    data["line"] = line
                data["advice"] = width_advice(c, data, gap)
                # Time lost against your best ever through this corner (any lap).
                best = track.mastery.get(c.number, {}).get("best_s")
                data["loss_s"] = round(data["time_s"] - best, 3) if best is not None else None
        run = self._optimal_run(ctx, wait=False)
        if lap and run and run.get("rows"):
            for data in lap:
                o = run["rows"].get(data["corner"])
                if o:
                    data["opt"] = {k: o.get(k) for k in OPT_KEYS}
                    data["opt_notes"] = compare_notes(data, o, "the optimal run")[:3]
        compare, compare_label = None, None
        if lap:
            ref_id = ctx.ref_lap_id
            if compare_id is None:
                if ref_id is not None and ref_id != lap_id:
                    compare_id = ref_id
                else:
                    others = [i for i in self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=500) if i != lap_id]
                    ranked = sorted(others, key=lambda i: (self.store.lap(i) or {}).get("lap_time_ms") or 1e12)
                    compare_id = ranked[0] if ranked else None
            if compare_id is not None and compare_id != lap_id:
                compare = self.store.lap_corners(compare_id, sig)
                if compare is None:
                    tr = self.store.trace(compare_id)
                    if tr:
                        self._analyse(compare_id, tr, track)
                        compare = self.store.lap_corners(compare_id, sig)
                info = self.store.lap(compare_id)
                is_best = compare_id == ref_id
                compare_label = "your best lap" if is_best else f"lap {info['lap_number']}" if info else "the other lap"
            if compare:
                by_num = {c["corner"]: c for c in compare}
                for other in compare:
                    k = other["corner"] - 1
                    line = line_vs_optimal(m.corners[k], other, m) if 0 <= k < len(m.corners) else None
                    if line:
                        other["line"] = line
                for data in lap:
                    other = by_num.get(data["corner"])
                    if other:
                        data["vs_s"] = round(data["time_s"] - other["time_s"], 3)
                        data["notes"] = compare_notes(data, other, compare_label)
        chapters = self._chapter_times(lap_id, ctx)
        practice = self._practice_times(lap_id, ctx)
        profile = self.car_profile if ctx.live else self.store.car_profile(ctx.game, ctx.car)
        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        systems = analyse_systems(lap_trace, track.model, profile) if lap_trace else None
        review = None
        if lap:
            # Your usual: your recent clean laps, not counting this one.
            history = [d for d in (self.store.lap_corners(i, sig)
                                   for i in self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=31)
                                   if i != lap_id) if d][:30]
            review = lap_review(lap, history, lap_trace, track.model, self.config["laps"]["max_tyres_out"])
        secs = self.store.best_sectors(ctx.game, ctx.track_key, ctx.car)
        tb = self._time_to_beat(ctx)
        if lap and tb:
            targets = {c["corner"]: c["target_s"] for c in tb["corners"]}
            for data in lap:
                data["to_beat_s"] = targets.get(data["corner"])
        return {
            "time_to_beat": tb,
            "game": ctx.game,
            "car": ctx.car,
            "track_key": ctx.track_key,
            "live": ctx.live,
            "theoretical_best_ms": sum(secs) if secs else None,
            "systems": systems,
            "review": review,
            "car_systems": car_profile.summary(profile) if profile else [],
            "compare": compare,
            "compare_lap_id": compare_id if compare else None,
            "compare_label": compare_label,
            "chapters": chapters,
            "practice": practice,
            "mastery": list(track.mastery.values()),
            "lap_id": lap_id,
            "lap": lap,
            "reference": list(track.ref_corners.values()),
            "reference_lap_id": ctx.ref_lap_id,
            "optimal": {"lap_s": run["lap_s"], "grip": run["grip"], "laps_used": run["laps_used"]}
            if run and run.get("trace") else None,
        }

    def _chapter_times(self, lap_id: int | None, ctx: AnalysisCtx) -> list[dict[str, Any]]:
        """Each pack chapter with this lap's time through it and your reference lap's."""
        if not ctx.track.model.chapters:
            return []

        def span(view: LapView | None, a: float, b: float) -> float | None:
            if not view:
                return None
            if b > a:
                return round(view.time_at(b) - view.time_at(a), 3)
            return None  # runs over the line: needs two laps

        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        view = LapView(lap_trace) if lap_trace else None
        ref = ctx.track.ref_view
        out = []
        for ch in ctx.track.model.chapters:
            d = ch.to_dict()
            d["time_s"] = span(view, ch.start, ch.end)
            d["ref_s"] = span(ref, ch.start, ch.end)
            out.append(d)
        return out

    def _practice_times(self, lap_id: int | None, ctx: AnalysisCtx) -> list[dict[str, Any]]:
        """Each practice section with this lap's time, your best lap's, and your
        best clean drill attempt."""

        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        view = LapView(lap_trace) if lap_trace else None
        ref = ctx.track.ref_view

        def span(v: LapView | None, a: float, b: float) -> float | None:
            return round(v.time_at(b) - v.time_at(a), 3) if v and b > a else None

        out = []
        for ps in ctx.track.model.practice:
            d = ps.to_dict()
            d["time_s"] = span(view, ps.start, ps.end)
            d["ref_s"] = span(ref, ps.start, ps.end)
            best = self.store.best_section_ms(ctx.game, ctx.car, ctx.track_key, ps.start, ps.end)
            d["drill_best_s"] = best / 1000 if best else None
            stretch = self._span_to_beat(ctx, ps.start, ps.end)
            d["to_beat_s"] = stretch["to_beat_s"] if stretch else None
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

    # -- optimal run --------------------------------------------------------------

    def _optimal_run(self, ctx: AnalysisCtx | None, wait: bool) -> dict[str, Any] | None:
        """The optimal line driven at this car's grip (see optimal_run.py), kept
        until your fastest laps change. ``wait=False`` never blocks: it returns
        what's known (maybe from before your latest laps) and works out a fresh
        one in the background, sending the live analysis again when it's done."""
        if ctx is None:
            return None
        key = (ctx.game, ctx.car, ctx.track_key)
        model = ctx.track.model
        ids = self.store.fastest_valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=OPT_LAPS)
        sig = (tuple(ids), model.optimal_ready())
        known = self._opt_runs.get(key)
        if known is not None and known["sig"] == sig:
            return known
        if wait:
            self._opt_runs[key] = run = self._work_out_run(model, ids, sig)
            return run
        if key not in self._opt_busy:
            self._opt_busy.add(key)
            threading.Thread(
                target=self._optimal_run_bg, args=(key, ctx.live, model, ids, sig), daemon=True, name="optimal-run"
            ).start()
        return known

    def _optimal_run_bg(self, key: tuple[str, str, str], live: bool, model: TrackModel, ids: list[int], sig: tuple) -> None:
        try:
            run = self._work_out_run(model, ids, sig)
        finally:
            self._opt_busy.discard(key)
        with self.lock:
            self._opt_runs[key] = run
            s = self.session
            if live and self.track is not None and s is not None and (s.game, s.car, s.track_key) == key:
                self._apply_target()
                self._emit_corners(None)

    def _apply_target(self, touch: bool = True) -> None:
        """Point the brake cue at the optimal run (if it's worked out and the
        setting says so), else at your best lap."""
        if self.track is None:
            return
        mode = self.config["coach"]["brake_cue"]
        self._cue_mode = mode
        s = self.session
        run = self._opt_runs.get((s.game, s.car, s.track_key)) if s is not None and mode == "optimal" else None
        tr = run.get("trace") if run else None
        self.track.set_target(tr, run.get("rows") if tr and run else None)
        if touch:
            self.csp.touch()  # the in-game app fetches the new braking points

    def _work_out_run(self, model: TrackModel, ids: list[int], sig: tuple) -> dict[str, Any]:
        run: dict[str, Any] = {"sig": sig}
        try:
            traces = [t for t in (self.store.trace(i) for i in ids) if t]
            grip = learn_grip(traces)
            tr = simulate(model, grip) if grip else None
            if grip and tr:
                run.update(
                    trace=tr,
                    lap_s=round(lap_time(tr), 3),
                    grip=grip.to_dict(),
                    laps_used=len(traces),
                    rows={r["corner"]: r for r in analyse_lap(tr, model)},
                )
        except Exception:  # noqa: BLE001 - the analysis works without it
            log.exception("Couldn't work out the optimal run for %s", model.track_key)
        return run

    def optimal_trace(self, game: str | None, car: str | None, track_key: str | None) -> dict[str, Any] | None:
        """The optimal run as a lap trace for the charts (about every 4 m)."""
        ctx = self.analysis_ctx(game, car, track_key)
        if ctx is None:
            return None
        if ctx.live:
            with self.lock:
                run = self._optimal_run(ctx, wait=False)
        else:
            run = self._optimal_run(ctx, wait=True)
        tr = run.get("trace") if run else None
        if not tr:
            return None
        n = len(tr["t"])
        step = max(1, round(4.0 / max(0.1, ctx.track.model.length_m / max(1, n))))
        return {"lap_s": run["lap_s"], "trace": {k: v[::step] for k, v in tr.items()}}

    def _emit_corners(self, lap_id: int | None) -> None:
        if self.track is not None:
            self.track.mastery = self._mastery()
            tb = self._time_to_beat(self._live_ctx())
            self.time_to_beat_ms = tb["lap_ms"] if tb else None
        self.emit({"type": "corners", **self.corner_report(lap_id)})

    # -- time to beat ---------------------------------------------------------------

    def _time_to_beat(self, ctx: AnalysisCtx | None) -> dict[str, Any] | None:
        """A realistic stretch target for the lap and each corner (see
        analysis.time_to_beat): your usual lap, minus what each corner's target
        asks of you. None until there are 3 clean laps."""
        if ctx is None:
            return None
        key = (ctx.game, ctx.car, ctx.track_key)
        ids = self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=TTB_LAPS)
        run = self._opt_runs.get(key)
        rows = run.get("rows") if run else None
        sig = (tuple(ids), id(rows), self._model_sig(ctx.track))
        known = self._ttb.get(key)
        if known is not None and known["sig"] == sig:
            return known["tb"]
        tb = None
        laps = [lap for lap in (self.store.lap(i) for i in ids) if lap and not lap.get("rewound")]
        if len(laps) >= 3:
            mastery = ctx.track.mastery or self._mastery(ctx)
            corners = time_to_beat(mastery, rows)
            usual = statistics.median(lap["lap_time_ms"] for lap in laps)
            gain_ms = sum(c["gain_s"] for c in corners.values()) * 1000
            # Every corner at its stretch at once adds up to more than one lap
            # realistically gives: never ask for much more than your best lap.
            best = self.store.best_lap(ctx.game, ctx.track_key, ctx.car)
            floor = best["lap_time_ms"] * (1 - TTB_PAST_BEST) if best else 0
            tb = {"lap_ms": round(min(usual, max(usual - gain_ms, floor))), "usual_lap_ms": round(usual),
                  "corners": sorted(corners.values(), key=lambda c: c["corner"])}
        self._ttb[key] = {"sig": sig, "tb": tb, "ids": ids, "views": None}
        return tb

    def _span_to_beat(self, ctx: AnalysisCtx | None, start_p: float, end_p: float) -> dict[str, float] | None:
        """Time to beat for a stretch of track (a drill, a practice section):
        your usual time through it over recent clean laps, minus what the
        corners in it ask of you. Seconds; None without enough laps."""
        tb = self._time_to_beat(ctx)
        if tb is None or ctx is None or not end_p > start_p:
            return None
        known = self._ttb[(ctx.game, ctx.car, ctx.track_key)]
        if known["views"] is None:
            known["views"] = [LapView(t) for t in (self.store.trace(i) for i in known["ids"]) if t]
        spans = [v.time_at(end_p) - v.time_at(start_p) for v in known["views"] if v]
        spans = [s for s in spans if s > 0]
        if len(spans) < 3:
            return None
        usual = statistics.median(spans)
        corners = {c.number: c for c in ctx.track.model.corners}
        gain = sum(c["gain_s"] for c in tb["corners"]
                   if c["corner"] in corners and start_p <= corners[c["corner"]].apex <= end_p)
        return {"usual_s": round(usual, 3), "to_beat_s": round(usual - gain, 3)}

    # -- drills -----------------------------------------------------------------

    @_locked
    def start_drill(self, start_p: float, end_p: float, name: str, corner: int | None = None) -> bool:
        s = self.session
        if self.track is None or s is None:
            return False
        drill = Drill(name=name, start_p=start_p % 1.0, end_p=end_p % 1.0, corner=corner)
        best = self.store.best_section_ms(s.game, s.car, s.track_key, drill.start_p, drill.end_p)
        span = self._span_to_beat(self._live_ctx(), drill.start_p, drill.end_p)
        self.track.start_drill(drill, best, int(span["to_beat_s"] * 1000) if span else None)
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

    RETRY_EXTRA_M = 600.0  # don't stop if somehow way further back than the target

    @_locked
    def start_retry(self) -> bool:
        if self.track is None or self.track.drill is None or self.frame is None:
            return False
        if self.csp.can_reset and self.csp.state.get("has_launch"):
            # The in-game app saved the car at the run-up point: it puts you
            # straight back there, at speed.
            self.csp.send({"cmd": "retry", "key": self._drill_key()})
            self._retry = {"t0": self._clock(), "csp": True}
            self.emit({"type": "retry", "state": "rewinding"})
            return True
        return self._retry_with_time_shift()

    def _retry_with_time_shift(self) -> bool:
        if self.track is None or self.track.drill is None or self.frame is None:
            return False
        if not self.keys.down(self.config["games"]["ac"]["rewind_key"]):
            return False
        lead_s = float(self.config["drills"]["lead_in_s"])
        target = self.track.lead_in_m(self.track.drill.drill, lead_s)
        self._retry = {"t0": self._clock(), "p0": self.frame.lap_progress, "moved": 0.0, "target_m": target}
        self.emit({"type": "retry", "state": "rewinding"})
        return True

    def _retry_step(self, f: Frame, now: float) -> None:
        r = self._retry
        assert r is not None and self.track is not None
        if r.get("csp"):
            if now - r["t0"] > 2.0:  # the app didn't answer: rewind with Time Shift instead
                self._retry = None
                self._retry_with_time_shift()
            return
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
            if r["target_m"] <= behind_m <= r["target_m"] + self.RETRY_EXTRA_M and r["moved"] > 1:
                done = "ready"
            elif now - r["t0"] > 1.5 and r["moved"] < 1:
                done = "no_rewind"  # Time Shift didn't react: key not bound?
            elif now - r["t0"] > 20:
                done = "timeout"
        if done:
            self.keys.up()
            self._retry = None
            self.emit({"type": "retry", "state": done})

    # -- getting to a drill: teleport (in-game app, offline) --------------------

    TELEPORT_EXTRA_M = 50.0  # always park a bit before the Time Shift run-up

    @_locked
    def teleport_to_drill(self) -> bool:
        """Park the car, stopped, far enough before the drill that pulling away
        flat out gets you to the section at your usual speed. Only to get there:
        retries rewind as normal."""
        if self.track is None or self.track.drill is None or not self.csp.can_reset:
            return False
        d = self.track.drill.drill
        run_up = self.track.lead_in_m(d, float(self.config["drills"]["lead_in_s"]))
        back = self.track.standing_start_m(d, min_m=run_up + self.TELEPORT_EXTRA_M)
        p = (d.start_p - back / self.track.model.length_m) % 1.0
        self.csp.send({"cmd": "teleport", "key": self._drill_key(), "p": p})
        self.emit({"type": "retry", "state": "teleporting"})
        return True

    # -- in-game CSP app ------------------------------------------------------

    def _drill_key(self) -> str | None:
        d = self.track.drill.drill if self.track and self.track.drill else None
        return f"{d.start_p:.5f}-{d.end_p:.5f}" if d else None

    def _csp_drill(self) -> dict[str, Any] | None:
        if self.track is None or self.track.drill is None:
            return None
        d = self.track.drill.drill
        lead = self.track.lead_in_m(d, float(self.config["drills"]["lead_in_s"]))
        st = self.track.drill
        # The in-game timer's target: the time to beat while it's quicker than
        # your best run, else your best (same as the side screen).
        target = st.target_ms if st.target_ms and (not st.best_ms or st.target_ms < st.best_ms) else st.best_ms
        return {
            "key": self._drill_key(),
            "name": d.name,
            "start_p": d.start_p,
            "end_p": d.end_p,
            "run_up_p": (d.start_p - lead / self.track.model.length_m) % 1.0,
            "target_ms": target,
            "target_is_best": target is not None and target == st.best_ms,
        }

    # -- car profile ----------------------------------------------------------

    def _load_car_profile(self) -> None:
        s = self.session
        if s is None:
            self.car_profile = None
            return
        self.car_profile = car_profile.from_session(s, self.store.car_profile(s.game, s.car))
        self._save_car_profile()

    def _save_car_profile(self) -> None:
        s, p = self.session, self.car_profile
        if s is None or p is None:
            return
        self.store.set_car_profile(s.game, s.car, p)
        self.emit({"type": "car_profile", "car_profile": p, "summary": car_profile.summary(p)})

    @_locked
    def csp_sync(self, body: dict[str, Any]) -> dict[str, Any]:
        """The in-game app checking in (about 10 times a second)."""
        was = self.csp.connected
        for e in self.csp.sync(body):
            if e.get("type") == "teleport":
                self.emit({"type": "retry", "state": "teleported" if e.get("ok") else "no_teleport"})
            if e.get("type") == "retry" and self._retry is not None and self._retry.get("csp"):
                self._retry = None
                if e.get("ok"):
                    self.emit({"type": "retry", "state": "ready"})
                else:
                    self._retry_with_time_shift()  # e.g. no saved state yet
        if not was:
            self.emit({"type": "csp", "connected": True})
        if self.car_profile is not None and car_profile.note_csp(self.car_profile, self.csp.state):
            self._save_car_profile()
        return {
            "track_version": self.csp.version if self.track is not None else -1,
            "drill": self._csp_drill(),
            "overlay": self.config["overlay"],  # set in Pitwall's Settings
            "commands": self.csp.take_commands(),
        }

    @_locked
    def csp_track(self) -> dict[str, Any] | None:
        """What the app needs to work out the next corner and brake point by itself."""
        if self.track is None:
            return None
        m = self.track.model
        ref = self.track.ref_corners
        cue_corners, v = self.track.cue()  # the optimal run, or your best lap
        corners = []
        for c in m.corners:
            r, t = ref.get(c.number, {}), cue_corners.get(c.number, {})
            corners.append({
                "n": c.number, "label": c.label, "dir": c.direction, "grade": c.grade,
                "entry": c.entry, "apex": c.apex, "exit": c.exit,
                "brake_p": t.get("brake_p"), "entry_kmh": t.get("entry_kmh"),
                "min_kmh": t.get("min_speed_kmh"), "min_p": t.get("min_speed_p"),
                "gear": r.get("apex_gear") or t.get("apex_gear") or None,
            })
        # The target's speed every 1/1000th of the lap, for the speed-adjusted brake point.
        speed = [round(v.trace["speed"][v.at(i / 1000)], 1) for i in range(1000)] if v else []
        return {"version": self.csp.version, "length_m": m.length_m, "corners": corners, "ref_speed": speed}

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
            # Real ABS / TC levels and brake bias from the in-game app (None without it).
            "electronics": self.csp.electronics(),
            "can_teleport": self.csp.can_reset,  # the in-game app is there, offline
            "delta_s": self.delta_s,
            "ref_lap_ms": self.reference.lap_time_ms if self.reference else None,
            "theoretical_best_ms": self.theoretical_best_ms,
            "time_to_beat_ms": self.time_to_beat_ms,
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
            "car_profile": self.car_profile,
            "car_systems": car_profile.summary(self.car_profile) if self.car_profile else [],
            "started_at": self.started_at,
            "recent_laps": self.recent_laps(),
            "track": self.track.model.geometry(compute_optimal=False) if self.track else None,
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


def _summary_targets(rep: dict[str, Any], model_corners: dict[int, Any]) -> dict[str, Any] | None:
    """The time to beat, condensed for the debrief: the lap, the corners with
    the most to gain, and the practice sections."""
    tb = rep.get("time_to_beat")
    if not tb:
        return None
    top = sorted(tb["corners"], key=lambda c: -c["gain_s"])[:4]
    return {
        "lap": fmt_ms(tb["lap_ms"]),
        "usual_lap": fmt_ms(tb["usual_lap_ms"]),
        "corners": [{"corner": model_corners[c["corner"]].label if c["corner"] in model_corners else f"Corner {c['corner']}",
                     "to_beat_s": c["target_s"], "usual_s": c["usual_s"], "why": c["why"]} for c in top],
        "practice_sections": [{"name": ps["name"], "to_beat_s": ps.get("to_beat_s")}
                              for ps in rep.get("practice", []) if ps.get("to_beat_s")],
    }


def fmt_ms(ms: int) -> str:
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"
