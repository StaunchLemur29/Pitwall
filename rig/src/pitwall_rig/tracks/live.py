"""Live track awareness: where you are across the track, what corner is next,
and timing for a practice section (drill)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..analysis import LapView, analyse_lap
from ..models import Frame, GameStatus
from .model import TrackModel


@dataclass
class Drill:
    name: str
    start_p: float
    end_p: float
    corner: int | None = None
    pass_within_s: float = 0.3  # an attempt counts if it's this close to your best…
    pass_streak: int = 3  # …and you need this many clean ones in a row

    def contains(self, p: float) -> bool:
        if self.start_p <= self.end_p:
            return self.start_p <= p <= self.end_p
        return p >= self.start_p or p <= self.end_p  # crosses the start line

    def length(self) -> float:
        return (self.end_p - self.start_p) % 1.0


@dataclass
class DrillState:
    drill: Drill
    best_ms: int | None = None  # best clean attempt ever (or from your best lap)
    attempts: int = 0
    streak: int = 0
    passed: bool = False
    running: bool = False
    elapsed_s: float = 0.0
    clean: bool = True
    last: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        d = asdict(self.drill)
        d.update(
            best_ms=self.best_ms,
            attempts=self.attempts,
            streak=self.streak,
            passed=self.passed,
            running=self.running,
            elapsed_s=round(self.elapsed_s, 2),
            last=self.last,
            recent=self.history[-8:],
        )
        return d


def _crossed(prev: float, now: float, mark: float) -> bool:
    """Did progress move forward past ``mark`` (handles the lap wrap)?"""
    if prev <= now:
        return prev < mark <= now
    return mark > prev or mark <= now  # wrapped past 1.0 → 0.0


class TrackState:
    def __init__(self, model: TrackModel, max_tyres_out: int = 2) -> None:
        self.model = model
        self.max_tyres_out = max_tyres_out
        self.ref_corners: dict[int, dict[str, Any]] = {}
        self.ref_view: LapView | None = None
        self.mastery: dict[int, dict[str, Any]] = {}
        self.drill: DrillState | None = None
        self._hint: int | None = None
        self._prev_p: float | None = None
        self._prev_t: float | None = None
        self.on_attempt = lambda attempt: None  # set by the rig to persist attempts

    # -- references -----------------------------------------------------------

    def set_reference(self, trace: dict[str, list[float]] | None) -> None:
        if not trace:
            self.ref_corners, self.ref_view = {}, None
            return
        self.ref_view = LapView(trace)
        self.ref_corners = {c["corner"]: c for c in analyse_lap(trace, self.model)}

    def ref_section_ms(self, d: Drill) -> int | None:
        v = self.ref_view
        if not v or d.start_p > d.end_p:
            return None
        return int((v.time_at(d.end_p) - v.time_at(d.start_p)) * 1000)

    # -- drills ---------------------------------------------------------------

    def start_drill(self, drill: Drill, best_ms: int | None) -> None:
        ref = self.ref_section_ms(drill)
        candidates = [b for b in (best_ms, ref) if b]
        self.drill = DrillState(drill, best_ms=min(candidates) if candidates else None)

    def stop_drill(self) -> None:
        self.drill = None

    def _drill_step(self, f: Frame, p: float, dt: float) -> dict[str, Any] | None:
        st = self.drill
        if st is None:
            return None
        d = st.drill
        prev = self._prev_p
        attempt = None
        if prev is not None:
            step = (p - prev) % 1.0
            if step > 0.5 and (1.0 - step) > 0.002:
                # Rewound (Time Shift) or reset: abandon the attempt, re-arm.
                st.running, st.elapsed_s = False, 0.0
            elif _crossed(prev, p, d.start_p):
                st.running, st.elapsed_s, st.clean = True, 0.0, True
            elif st.running and _crossed(prev, p, d.end_p):
                st.running = False
                time_ms = int(st.elapsed_s * 1000)
                attempt = self._record(st, time_ms)
        if st.running:
            st.elapsed_s += dt
            if f.tyres_out > self.max_tyres_out:
                st.clean = False
        return attempt

    def _record(self, st: DrillState, time_ms: int) -> dict[str, Any]:
        st.attempts += 1
        prev_best = st.best_ms
        delta = (time_ms - prev_best) / 1000 if prev_best else None
        good = st.clean and (prev_best is None or delta <= st.drill.pass_within_s)
        st.streak = st.streak + 1 if good else 0
        if st.clean and (prev_best is None or time_ms < prev_best):
            st.best_ms = time_ms
        if st.streak >= st.drill.pass_streak:
            st.passed = True
        st.last = {"time_ms": time_ms, "clean": st.clean, "delta_s": delta, "counted": good}
        st.history.append(st.last)
        attempt = {**st.last, "start_p": st.drill.start_p, "end_p": st.drill.end_p}
        self.on_attempt(attempt)
        return attempt

    # -- per frame ------------------------------------------------------------

    def update(self, f: Frame) -> dict[str, Any] | None:
        if f.status != GameStatus.LIVE or f.world is None:
            self._prev_p = None
            self._prev_t = None
            return None
        p = f.lap_progress % 1.0
        dt = 0.0 if self._prev_t is None else max(0.0, f.t - self._prev_t)
        m = self.model
        hint = self._hint if self._hint is not None else m.index_at(p)
        self._hint, off, frac = m.locate(f.world[0], f.world[2], hint)
        if abs(m.index_at(p) - self._hint) > 200:  # lost track (teleport/rewind): resync
            self._hint, off, frac = m.locate(f.world[0], f.world[2], m.index_at(p))

        out: dict[str, Any] = {
            "p": round(p, 5),
            "off_m": round(off, 2) if m.has_edges else None,
            "frac": round(frac, 3) if m.has_edges else None,
            "heading": self._heading(self._hint),
        }
        nxt = m.next_corner(p)
        if nxt is not None:
            c, dist = nxt
            ref = self.ref_corners.get(c.number, {})
            brake_in = None
            if ref.get("brake_p") is not None:
                brake_in = ((ref["brake_p"] - p) % 1.0) * m.length_m
                if brake_in > dist + 400:  # already past the braking point
                    brake_in = None
            mast = self.mastery.get(c.number, {})
            out["corner"] = {
                **c.to_dict(),
                "distance_m": round(dist),
                "brake_in_m": round(brake_in) if brake_in is not None else None,
                "gear": ref.get("apex_gear"),
                "apex_kmh": ref.get("min_speed_kmh"),
                "grade_mastery": mast.get("grade"),
            }
        attempt = self._drill_step(f, p, dt)
        if self.drill is not None:
            out["drill"] = self.drill.to_wire()
        if attempt is not None:
            out["attempt"] = attempt
        self._prev_p, self._prev_t = p, f.t
        return out

    def _heading(self, i: int) -> float:
        """Direction of travel in degrees in the (x, z) plane, for heading-up maps."""
        import math

        line = self.model.line
        n = len(line)
        a, b = (i - 3) % n, (i + 3) % n
        return round(math.degrees(math.atan2(line.z[b] - line.z[a], line.x[b] - line.x[a])), 1)
