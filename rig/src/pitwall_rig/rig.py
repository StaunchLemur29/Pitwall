"""The rig loop: poll the game, record laps, derive live values, emit events."""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from . import car_profile
from .adapters.base import GameAdapter
from .adapters.replay import Recorder
from .analysis import (
    LapView,
    analyse_lap,
    analyse_systems,
    compare_notes,
    corner_mastery,
    counts,
    lap_review,
    line_vs_optimal,
    width_advice,
)
from .conditions import Conditions
from .config import ACTIONS, Config
from .csp import CspLink
from .input import InputEvent
from .laps import LapRecorder
from .models import Frame, GameStatus, Lap, Mode, SessionInfo, mode_for
from .optimal_run import lap_time, learn_grip, simulate
from .reference import ReferenceLap, downsample
from .rig_coach import CoachMixin
from .rig_common import (
    OPT_KEYS,
    OPT_LAPS,
    OPTIMAL,
    AnalysisCtx,
    Event,
    _covers,
    _locked,
    _summary_targets,
    fmt_ms,
)
from .rig_drills import DrillsMixin
from .rig_pits import PitsMixin
from .rig_wheel import WheelMixin
from .storage import Store
from .tips import Tips
from .tracks.live import TrackState
from .tracks.loader import from_lap_trace
from .tracks.model import TrackModel

log = logging.getLogger(__name__)


# The optimal run learns the car's grip from this many of your fastest laps.
# What each corner row carries about the optimal run (also uploaded to the hub).


class Rig(CoachMixin, DrillsMixin, PitsMixin, WheelMixin):
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
        self._post_lap: Any = None  # queue of laps for the post-lap worker (None: do it straight away)
        self.sf1000: Any = None  # the wheel screen sender, while it's switched on
        self._ttb: dict[tuple[str, str, str], dict[str, Any]] = {}  # time to beat per car + track (cached)
        self.time_to_beat_ms: int | None = None  # the live car + track's lap time to beat
        # The side screen's coach strip: one focus for the session, the last lap's
        # biggest mistake, and a cold-tyre warning.
        self._focus: dict[str, Any] | None = None  # {corner, beaten}: the session's one focus corner
        self._focus_met: set[int] = set()  # focus corners already met this session
        self._last_rows: dict[int, dict[str, Any]] = {}  # the last lap's corners (for the focus fix)
        self._last_lap_note: dict[str, Any] | None = None
        self._tyre_sum, self._tyre_n = 0.0, 0  # this lap's tyre core temperature at speed
        self._tyres_cold = False
        self.conditions = Conditions()
        self.tips = Tips()  # live tips: one a lap, on the straight before the corner  # the track, weather, tyre wear and damage; notices when they change
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
        self.on_pit: Callable[[str, str, str], None] = lambda g, c, t: None  # e.g. write the AI debrief so far
        self.pit_report: dict[str, Any] | None = None  # how the stint went, while you're in the pits
        self._in_pits = False
        self._stint_t0 = time.time()  # when this stint started (you left the pits)
        self._stint_cond: dict[str, Any] | None = None
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
                except Exception:
                    log.exception("Session-end hook failed")
            self.session = session
            self.conditions.reset()
            self.tips.reset()
            self.pit_report, self._stint_t0, self._stint_cond = None, time.time(), None
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
        self._note_tyres(frame)
        self.conditions.update(frame, now)
        self._note_pits(frame)
        self.laps.max_tyres_out = self.config["laps"]["max_tyres_out"]
        self._feed_wheel(frame)
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

    # -- the pit report ------------------------------------------------------------


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

    def start_post_lap_worker(self) -> None:
        """Do the work after each lap (saving, analysis, the review) on its own
        thread, so crossing the line never stalls the live data. On a long lap
        (the Nordschleife) that work takes a few hundred ms. Without the worker
        (tests, scripts) it happens straight away, in order."""
        if self._post_lap is not None:
            return
        import queue

        self._post_lap = q = queue.Queue()

        def run() -> None:
            while True:
                lap = q.get()
                try:
                    self._finish_lap(lap)
                except Exception:
                    log.exception("Couldn't finish lap %s", lap.lap_number)

        threading.Thread(target=run, name="pitwall-post-lap", daemon=True).start()

    # -- the SF1000 wheel screen ------------------------------------------------------


    def _on_lap(self, lap: Lap) -> None:
        # Called from the telemetry thread as you cross the line: hand it on.
        lap.conditions = self.conditions.snapshot(self.frame)
        if self._post_lap is not None:
            self._post_lap.put(lap)
        else:
            self._finish_lap(lap)

    def _finish_lap(self, lap: Lap) -> None:
        """Save and analyse a finished lap. Holds the rig lock only for the quick
        state updates, so the live data keeps flowing meanwhile."""
        self.store.add_lap(lap)  # the store has its own lock
        with self.lock:
            self._learn_tyre_temp(lap)
            self.on_lap_saved()
            new_best = lap.valid and not lap.rewound and (
                self.reference is None or lap.lap_time_ms < self.reference.lap_time_ms)
            if new_best:
                self.reference = ReferenceLap(lap.trace, lap.lap_time_ms, lap.id)
            track = self.track
            reload = track is None or (track.model.source == "laps" and new_best)
            if reload:
                self._load_track()  # a first (or better) lap lets us draw a learnt map
        if not reload and track is not None:
            if new_best:
                track.set_reference(lap.trace)
                with self.lock:
                    self.csp.touch()
            if lap.id is not None:  # every lap: the corners it drove well count, finished or not
                self._analyse(lap.id, lap.trace, track)
                self._record_sections(lap, track)
            self._emit_corners(lap.id)
        with self.lock:
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
        except Exception:
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
        self._focus, self._focus_met, self._last_rows, self._last_lap_note = None, set(), {}, None
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
        # Laps from before every lap's section passes were kept: fill them in, in
        # the background, so your section bests count from all your laps here.
        if self.store.laps_without_sections(s.game, s.track_key, s.car, limit=1):
            threading.Thread(target=self._backfill_sections, args=(s.game, s.car, s.track_key, self.track),
                             daemon=True, name="section-backfill").start()
        if not model.optimal_ready():
            # A few seconds on a long track: work it out off the telemetry thread,
            # then send the map (and the corner tips that use it) again.
            threading.Thread(target=self._optimal_line, args=(model,), daemon=True, name="optimal-line").start()

    def _backfill_sections(self, game: str, car: str, track_key: str, track: TrackState) -> None:
        n = 0
        try:
            for lap_id in self.store.laps_without_sections(game, track_key, car):
                info, trace = self.store.lap(lap_id), self.store.trace(lap_id)
                if info is None:
                    continue
                lap = Lap(game=game, car=car, track_key=track_key, lap_number=info["lap_number"],
                          lap_time_ms=info["lap_time_ms"], valid=info["valid"], out_lap=info["out_lap"],
                          started_at=info["started_at"], trace=trace or {}, id=lap_id,
                          rewound=bool(info.get("rewound")), unfinished=bool(info.get("unfinished")))
                self._record_sections(lap, track)
                n += 1
        except Exception:
            log.exception("Couldn't fill in the section bests of older laps")
        if n:
            log.info("Section bests: filled in %d older laps on %s", n, track_key)

    def _optimal_line(self, model: TrackModel) -> None:
        try:
            model.optimal()
        except Exception:
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
        return f"v5:{m.source}:{len(m.corners)}:{round(m.length_m)}"  # v5: driven / clean per corner

    def _analyse(self, lap_id: int, trace: dict[str, list[float]], track: TrackState | None = None) -> None:
        track = track or self.track
        if track is None:
            return
        self.store.set_lap_corners(lap_id, self._model_sig(track),
                                   analyse_lap(trace, track.model, self.config["laps"]["max_tyres_out"]))

    def _record_sections(self, lap: Lap, track: TrackState) -> None:
        """Keep this lap's clean passes through each practice section, so your best
        through a section counts even if the lap was an out lap or you crashed
        later. Not from a lap with a rewind (never a best), not a section you
        went off in, and only where the lap was driven all the way through it."""
        if lap.id is None:
            return
        if lap.rewound or not lap.trace.get("p"):
            self.store.add_lap_sections(lap.id, lap.game, lap.car, lap.track_key, [])  # looked at: nothing counts
            return
        view = LapView.of(lap.trace)
        off = lap.trace.get("off") or []
        limit = self.config["laps"]["max_tyres_out"]
        passes = []
        for ps in track.model.practice:
            a, b = ps.start, ps.end
            if not (b > a and _covers(view, a, b)):
                continue  # runs over the line, or the lap didn't drive all of it
            i, j = view.at(a), view.at(b)
            ts = lap.trace["t"][i:j + 1]
            if any(t2 - t1 > 0.5 or t2 < t1 for t1, t2 in itertools.pairwise(ts)):
                continue  # a gap in the telemetry: not driven through in one go
            if any(o > limit for o in off[i:j + 1]):
                continue
            ms = round((view.time_at(b) - view.time_at(a)) * 1000)
            if ms > 0:
                passes.append((a, b, ms))
        self.store.add_lap_sections(lap.id, lap.game, lap.car, lap.track_key, passes)

    def _history(self, ctx: AnalysisCtx, exclude: int | None = None, limit: int = 30,
                 skip_rewound: bool = False) -> list[list[dict[str, Any]]]:
        """Your recent driving through each corner, newest lap first: the corners
        that count (driven all the way, clean) from any lap, finished or not,
        valid or cut somewhere else. Analyses laps that haven't been yet."""
        sig = self._model_sig(ctx.track)
        out: list[list[dict[str, Any]]] = []
        for info in self.store.laps(ctx.game, ctx.track_key, ctx.car, limit=limit * 3):
            if info["id"] == exclude or (skip_rewound and info.get("rewound")):
                continue
            data = self.store.lap_corners(info["id"], sig)
            if data is None:
                tr = self.store.trace(info["id"])
                if tr:
                    self._analyse(info["id"], tr, ctx.track)
                    data = self.store.lap_corners(info["id"], sig)
            good = [c for c in data or [] if counts(c, info["valid"])]
            if good:
                out.append(good)
            if len(out) >= limit:
                break
        return out

    def _best_corners(self, ctx: AnalysisCtx, lap_id: int | None) -> list[dict[str, Any]]:
        """Your quickest pass through each corner on any other lap (finished or
        not, valid or cut elsewhere), excluding laps with a rewind."""
        best: dict[int, dict[str, Any]] = {}
        for lap in self._history(ctx, exclude=lap_id, limit=60, skip_rewound=True):
            for c in lap:
                b = best.get(c["corner"])
                if b is None or c["time_s"] < b["time_s"]:
                    best[c["corner"]] = c
        return [best[k] for k in sorted(best)]

    def _mastery(self, ctx: AnalysisCtx | None = None) -> dict[int, dict[str, Any]]:
        ctx = ctx or self._live_ctx()
        if ctx is None:
            return {}
        return corner_mastery(self._history(ctx))

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
        except Exception:
            log.exception("Couldn't load the track layout for %s", track_key)
        if model is None:
            lap_id = self.store.outline_lap_id(game, track_key)
            trace = self.store.trace(lap_id) if lap_id is not None else None
            if trace:
                model = from_lap_trace(track_key, trace, 0.0)
        if model is not None:
            try:
                model.optimal()  # outside the lock too: seconds on a long track, once
            except Exception:
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
            "conditions_on_best_lap": rep.get("conditions"),
            "corners_on_best_lap": corners,
            "practice_sections": [
                {"name": ps["name"], "this_lap_s": ps.get("time_s"), "best_lap_s": ps.get("ref_s"),
                 "your_best_s": ps.get("drill_best_s")}
                for ps in rep.get("practice", [])
            ],
            "battery_and_drs": (rep.get("systems") or {}).get("notes", []),
            "car_has": rep.get("car_systems", []),
            # Realistic stretch targets (your usual, part of the way to your best or the optimal run).
            "time_to_beat": _summary_targets(rep, model_corners),
        }

    def tools(self, game: str | None = None, car: str | None = None, track_key: str | None = None) -> dict[str, Any]:
        """Hardware checks from your last 10 clean laps of this car + track:
        force feedback clipping (TS-PC) and how you use the brake (T-LCM)."""
        from .tools import ffb_report, pedal_report

        ctx = self.analysis_ctx(game, car, track_key)
        if ctx is None:
            return {"car": None, "track_key": None, "ffb": None, "pedals": None}
        ids = self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=10)
        traces = [t for t in (self.store.trace(i) for i in ids) if t]
        return {"game": ctx.game, "car": ctx.car, "track_key": ctx.track_key,
                "ffb": ffb_report(traces, ctx.track.model), "pedals": pedal_report(traces)}

    def blind_spots(self, game: str | None = None, car: str | None = None, track_key: str | None = None) -> dict[str, Any]:
        """Habits your recent laps on this car + track show (see scan.py)."""
        from .analysis import corner_mastery
        from .scan import blind_spots
        from .tools import pedal_report

        ctx = self.analysis_ctx(game, car, track_key)
        if ctx is None:
            return {"findings": [], "laps": 0}
        history = self._history(ctx, limit=20)
        if ctx.live:
            with self.lock:
                run = self._optimal_run(ctx, wait=False)
        else:
            run = self._optimal_run(ctx, wait=True)
        ids = self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=10)
        pedals = pedal_report([t for t in (self.store.trace(i) for i in ids) if t])
        found = blind_spots(history, ctx.track.model.corners, (run or {}).get("rows"), pedals,
                            ctx.track.model.practice, corner_mastery(history))
        return {"findings": found, "laps": len(history)}

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
            self._optimal_run(ctx, wait=True)  # reads a few laps
        # Not under the rig lock: on a long track this takes a moment, and the
        # live data mustn't wait for it. It works from ``ctx`` and the store.
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
                if c is None or data.get("driven") is False:
                    continue  # not driven on this lap (didn't finish it, or jumped past): nothing to say
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
                if o and data.get("driven") is not False:
                    data["opt"] = {k: o.get(k) for k in OPT_KEYS}
                    data["opt_notes"] = compare_notes(data, o, "the optimal run")[:3]
        compare, compare_label, compare_kind = None, None, None
        if lap:
            ref_id = ctx.ref_lap_id
            if compare_id is None:
                # Coaching, not lap comparison: only ever against something faster.
                # Your best lap if it's quicker than this one; on your best (or a
                # lap quicker only by cutting), the benchmark: the optimal run.
                shown_info = self.store.lap(lap_id) if lap_id is not None else None
                ref_info = self.store.lap(ref_id) if ref_id is not None else None
                full_lap = bool(shown_info) and not shown_info["out_lap"] and not shown_info.get("unfinished")
                if ref_info and ref_id != lap_id and (not full_lap or ref_info["lap_time_ms"] < shown_info["lap_time_ms"]):
                    compare_id = ref_id
                else:
                    compare_id = OPTIMAL
            if compare_id == OPTIMAL:
                rows = run.get("rows") if run else None
                if rows:
                    compare_kind, compare_label = "optimal", "the optimal run"
                    compare = [dict(rows[c.number]) for c in m.corners if c.number in rows]
                    for data in lap:
                        o = rows.get(data["corner"])
                        if o and data.get("driven") is not False:
                            data["vs_s"] = round(data["time_s"] - o["time_s"], 3)
                            data["notes"] = data.get("opt_notes") or compare_notes(data, o, compare_label)[:3]
                else:
                    # No optimal run yet (it needs the track's edges, a few clean
                    # laps and a moment to work out): compare with your best
                    # through each corner on any lap instead. Never slower than
                    # this lap, so still only ever against something faster.
                    compare = self._best_corners(ctx, lap_id)
                    if compare:
                        compare_kind, compare_label = "best_corners", "your best here"
                        by_num = {c["corner"]: c for c in compare}
                        for data in lap:
                            o = by_num.get(data["corner"])
                            if o and data.get("driven") is not False:
                                data["vs_s"] = round(data["time_s"] - o["time_s"], 3)
                                data["notes"] = compare_notes(data, o, compare_label)[:3] if data["vs_s"] > 0.02 else []
                compare_id = None
            elif compare_id is not None and compare_id != lap_id:
                compare_kind = "lap"
                compare = self.store.lap_corners(compare_id, sig)
                if compare is None:
                    tr = self.store.trace(compare_id)
                    if tr:
                        self._analyse(compare_id, tr, track)
                        compare = self.store.lap_corners(compare_id, sig)
                info = self.store.lap(compare_id)
                is_best = compare_id == ref_id
                compare_label = "your best lap" if is_best else f"lap {info['lap_number']}" if info else "the other lap"
            if compare and compare_kind == "lap":
                by_num = {c["corner"]: c for c in compare}
                for other in compare:
                    k = other["corner"] - 1
                    line = line_vs_optimal(m.corners[k], other, m) if 0 <= k < len(m.corners) else None
                    if line:
                        other["line"] = line
                for data in lap:
                    other = by_num.get(data["corner"])
                    if other and data.get("driven") is not False and other.get("driven") is not False:
                        data["vs_s"] = round(data["time_s"] - other["time_s"], 3)
                        data["notes"] = compare_notes(data, other, compare_label)
        chapters = self._chapter_times(lap_id, ctx)
        practice = self._practice_times(lap_id, ctx)
        profile = self.car_profile if ctx.live else self.store.car_profile(ctx.game, ctx.car)
        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        systems = analyse_systems(lap_trace, track.model, profile) if lap_trace else None
        review = None
        if lap:
            # Your usual: your recent driving, not counting this lap.
            history = self._history(ctx, exclude=lap_id)
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
            "compare_kind": compare_kind,  # "lap" | "optimal" | None
            "chapters": chapters,
            "practice": practice,
            "mastery": list(track.mastery.values()),
            "lap_id": lap_id,
            "lap": lap,
            "reference": list(track.ref_corners.values()),
            "reference_lap_id": ctx.ref_lap_id,
            # the track, weather, tyre wear and damage on this lap (and the lap it's compared with)
            "conditions": self.store.lap_conditions(lap_id) if lap_id is not None else None,
            "compare_conditions": self.store.lap_conditions(compare_id) if compare and compare_kind == "lap" else None,
            "optimal": {"lap_s": run["lap_s"], "grip": run["grip"], "laps_used": run["laps_used"]}
            if run and run.get("trace") else None,
        }

    def _chapter_times(self, lap_id: int | None, ctx: AnalysisCtx) -> list[dict[str, Any]]:
        """Each pack chapter with this lap's time through it and your reference lap's."""
        if not ctx.track.model.chapters:
            return []

        def span(view: LapView | None, a: float, b: float) -> float | None:
            if not view or not _covers(view, a, b):
                return None  # an unfinished lap that didn't drive all of it
            if b > a:
                return round(view.time_at(b) - view.time_at(a), 3)
            return None  # runs over the line: needs two laps

        lap_trace = self.store.trace(lap_id) if lap_id is not None else None
        view = LapView.of(lap_trace) if lap_trace else None
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
        view = LapView.of(lap_trace) if lap_trace else None
        ref = ctx.track.ref_view

        def span(v: LapView | None, a: float, b: float) -> float | None:
            return round(v.time_at(b) - v.time_at(a), 3) if v and b > a and _covers(v, a, b) else None

        out = []
        drilled = self.store.best_sections(ctx.game, ctx.car, ctx.track_key)  # one query, not one per section
        tb = self._time_to_beat(ctx)
        for ps in ctx.track.model.practice:
            d = ps.to_dict()
            d["time_s"] = span(view, ps.start, ps.end)
            d["ref_s"] = span(ref, ps.start, ps.end)
            best = next((ms for a, b, ms in drilled if abs(a - ps.start) < 1e-4 and abs(b - ps.end) < 1e-4), None)
            d["drill_best_s"] = best / 1000 if best else None
            stretch = self._span_to_beat(ctx, ps.start, ps.end, tb)
            d["to_beat_s"] = stretch["to_beat_s"] if stretch else None
            out.append(d)
        return out


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
        except Exception:
            log.exception("Couldn't work out the optimal run for %s", model.track_key)
        return run

    def cloud_combo(self, game: str, car: str, track_key: str) -> dict[str, Any] | None:
        """What the hub needs per car + track that isn't in any one lap: the
        optimal run (about every 4 m), your best drill run through each section
        and the blind-spot scan."""
        opt = self.optimal_trace(game, car, track_key)
        if opt:
            keep = ("t", "p", "x", "z", "speed", "gas", "brake", "gear")
            opt = {"lap_s": opt["lap_s"], "trace": {k: v for k, v in opt["trace"].items() if k in keep}}
        drills = self.store.best_drill_runs(game, car, track_key)
        # The blind-spot scan too (the hub can't run it: it needs every recent lap's corners).
        scan = self.blind_spots(game, car, track_key)
        scan = {"findings": scan["findings"], "laps": scan["laps"]} if scan.get("laps") else None
        return {"optimal": opt, "drill_bests": drills, "blind_spots": scan} if opt or drills or scan else None

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
        tb = None
        track = self.track
        if track is not None:
            track.mastery = self._mastery()
            tb = self._time_to_beat(self._live_ctx())
            self.time_to_beat_ms = tb["lap_ms"] if tb else None
        rep = self.corner_report(lap_id)
        if lap_id is not None and self.track is not None:
            self._coach_after_lap(lap_id, rep, tb)
        elif self._focus is None:
            self._pick_focus(tb)  # e.g. on arriving: from your earlier laps
        self.emit({"type": "corners", **rep})

    # -- the coach strip (side screen) ---------------------------------------------


    # -- time to beat ---------------------------------------------------------------


    # -- drills -----------------------------------------------------------------


    # -- automatic retry (hold Time Shift until we're back before the section) --


    # -- getting to a drill: teleport (in-game app, offline) --------------------


    # -- in-game CSP app ------------------------------------------------------


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
            # systems this car really has (seen working), so the side screen only shows those
            "car_has": {"drs": car_profile.has_drs(self.car_profile), "battery": car_profile.has_battery(self.car_profile)},
            "delta_s": self.delta_s,
            "ref_lap_ms": self.reference.lap_time_ms if self.reference else None,
            "theoretical_best_ms": self.theoretical_best_ms,
            "time_to_beat_ms": self.time_to_beat_ms,
            "coach": self._coach_live(),
            "pit_report": self.pit_report,
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

    FASTEST_IN_LIST = 10

    def recent_laps(self, limit: int = 30) -> list[dict[str, Any]]:
        """The latest laps on this car + track, plus your fastest ones however old
        they are: the analysis compares with faster laps, so your best must be in
        the list even after hundreds of newer laps."""
        s = self.session
        if s is None:
            return []
        out = self.store.laps(s.game, s.track_key, s.car, limit=limit)
        have = {x["id"] for x in out}
        for lap_id in self.store.fastest_valid_lap_ids(s.game, s.track_key, s.car, limit=self.FASTEST_IN_LIST):
            if lap_id not in have:
                info = self.store.lap(lap_id)
                if info is not None:
                    out.append(info)
        out.sort(key=lambda x: x["started_at"], reverse=True)
        return out

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


