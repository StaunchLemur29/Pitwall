"""Live track awareness: where you are across the track, what corner is next,
and timing for a practice section (drill)."""

from __future__ import annotations

import math
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


def _angdiff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


class YawCalibrator:
    """Works out how the game's heading angle maps onto map directions.

    Games differ in where zero points and which way angles turn. While you drive
    straight-ish at speed, the car points where it's going, so we compare the
    raw heading with the direction of travel and keep the mapping that fits.
    """

    CANDIDATES = [(s, o) for s in (1, -1) for o in (0.0, 90.0, 180.0, -90.0)]

    def __init__(self) -> None:
        self.err = [0.0] * len(self.CANDIDATES)
        self.samples = 0
        self.best: tuple[int, float] | None = None

    def observe(self, yaw_rad: float, travel_deg: float) -> None:
        y = math.degrees(yaw_rad)
        for i, (sgn, off) in enumerate(self.CANDIDATES):
            e = abs(_angdiff(sgn * y + off, travel_deg))
            self.err[i] = self.err[i] * 0.98 + e * 0.02 if self.samples else e
        self.samples += 1
        if self.samples >= 60:
            i = min(range(len(self.err)), key=self.err.__getitem__)
            if self.err[i] < 20:
                self.best = self.CANDIDATES[i]

    def heading(self, yaw_rad: float) -> float | None:
        if self.best is None:
            return None
        sgn, off = self.best
        return (sgn * math.degrees(yaw_rad) + off + 180.0) % 360.0 - 180.0


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
        self._prev_lap: tuple[int, int] | None = None  # (lap, lap_time_ms)
        self.yaw = YawCalibrator()
        self._shift_corner: int | None = None  # corner the braking-point shift belongs to
        self._shift = 0.0  # metres earlier (+) than the reference braking point
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

    def lead_in_m(self, d: Drill, seconds: float, fallback_mps: float = 40.0) -> float:
        """How far before the section start is ``seconds`` of driving, going by
        your reference lap (or a typical speed if there isn't one yet)."""
        length = self.model.length_m or 1.0
        v = self.ref_view
        if v:
            t_start = v.time_at(d.start_p)
            if t_start - seconds > v.trace["t"][v.idx[0]] + 0.5:
                p = v.progress_at(t_start - seconds)
                return max(30.0, ((d.start_p - p) % 1.0) * length)
        return seconds * fallback_mps

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
            self._prev_lap = None
            return None
        p = f.lap_progress % 1.0
        dt = self._game_dt(f)
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
            "car_heading": self._car_heading(f),
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
                else:
                    brake_in -= self._speed_shift(c.number, ref, p, f.speed_kmh)
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
        self._prev_lap = (f.lap, f.lap_time_ms)
        return out

    def _speed_shift(self, corner: int, ref: dict[str, Any], p: float, speed_kmh: float) -> float:
        """How much earlier (+) or later (-) to brake than on your reference lap,
        given how fast you're arriving.

        Takes the reference lap's braking (from its speed at the brake point
        down to its slowest point, over the distance it used) as how hard the
        car can brake, then works out the distance your speed needs. Your speed
        at the braking point is predicted as the reference's plus the gap you
        have to it right now, so it settles as you get closer.
        """
        if self._shift_corner != corner:
            self._shift_corner, self._shift = corner, 0.0
        v = self.ref_view
        ve, vmin, bp, mp = ref.get("entry_kmh"), ref.get("min_speed_kmh"), ref.get("brake_p"), ref.get("min_speed_p")
        if not v or ve is None or vmin is None or bp is None or mp is None or ve - vmin < 15:
            return self._shift
        d_ref = ((mp - bp) % 1.0) * self.model.length_m
        if not 5 < d_ref < 600:
            return self._shift
        ref_now = v.trace["speed"][v.at(p)]
        vb = max(vmin + 1, ve + (speed_kmh - ref_now))  # your predicted speed at the brake point
        d_you = d_ref * (vb**2 - vmin**2) / (ve**2 - vmin**2)
        limit = min(80.0, 0.5 * d_ref)
        target = max(-limit, min(limit, d_you - d_ref))
        self._shift += (target - self._shift) * 0.2  # smooth out pedal/speed noise
        return self._shift

    def _game_dt(self, f: Frame) -> float:
        """Time since the last frame by the game's own lap clock (so pauses and
        replay speed don't distort drill times); wall clock as a fallback."""
        prev = self._prev_lap
        if prev is not None and f.lap_time_ms > 0:
            lap, ms = prev
            if f.lap == lap and f.lap_time_ms >= ms:
                return (f.lap_time_ms - ms) / 1000.0
            if f.lap == lap + 1 and f.lap_time_ms < 2000:
                return f.lap_time_ms / 1000.0  # crossed the line; tail of the old lap is unknown but tiny
        return 0.0 if self._prev_t is None else min(0.5, max(0.0, f.t - self._prev_t))

    def _car_heading(self, f: Frame) -> float | None:
        """Where the car's nose points, in map degrees (None until known)."""
        travel = None
        if f.velocity is not None and f.speed_kmh > 10:
            travel = math.degrees(math.atan2(f.velocity[2], f.velocity[0]))
        if f.yaw is not None:
            if travel is not None and f.speed_kmh > 60 and abs(f.steer) < 0.15:
                self.yaw.observe(f.yaw, travel)
            h = self.yaw.heading(f.yaw)
            if h is not None:
                return round(h, 1)
        return round(travel, 1) if travel is not None else None

    def _heading(self, i: int) -> float:
        """Direction of travel in degrees in the (x, z) plane, for heading-up maps."""
        import math

        line = self.model.line
        n = len(line)
        a, b = (i - 3) % n, (i + 3) % n
        return round(math.degrees(math.atan2(line.z[b] - line.z[a], line.x[b] - line.x[a])), 1)
