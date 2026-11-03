"""Per-corner analysis of a lap trace against a TrackModel."""

from __future__ import annotations

import statistics
from bisect import bisect_left
from typing import Any

from .tracks.model import Corner, TrackModel


def _monotonic(trace: dict[str, list[float]]) -> list[int]:
    """Indices of samples with strictly increasing progress (drops the
    pre-line samples that still read ~0.99)."""
    ps, ts = trace.get("p", []), trace.get("t", [])
    keep: list[int] = []
    for i, (p, t) in enumerate(zip(ps, ts, strict=False)):
        if t < 5 and p > 0.9:
            continue
        if not keep or p > ps[keep[-1]]:
            keep.append(i)
    return keep


class LapView:
    """Lookups into one lap trace by track progress."""

    def __init__(self, trace: dict[str, list[float]]):
        self.trace = trace
        self.idx = _monotonic(trace)
        self.p = [trace["p"][i] for i in self.idx]

    def __bool__(self) -> bool:
        return len(self.idx) > 20

    def at(self, progress: float) -> int:
        """Trace index nearest to ``progress``."""
        j = min(max(bisect_left(self.p, progress), 0), len(self.p) - 1)
        if j > 0 and abs(self.p[j - 1] - progress) < abs(self.p[j] - progress):
            j -= 1
        return self.idx[j]

    def time_at(self, progress: float) -> float:
        j = bisect_left(self.p, progress)
        if j <= 0:
            return self.trace["t"][self.idx[0]]
        if j >= len(self.p):
            return self.trace["t"][self.idx[-1]]
        p0, p1 = self.p[j - 1], self.p[j]
        t0, t1 = self.trace["t"][self.idx[j - 1]], self.trace["t"][self.idx[j]]
        return t0 + (t1 - t0) * (progress - p0) / (p1 - p0)

    def progress_at(self, t: float) -> float:
        """Track progress at lap time ``t`` (clamped to the lap)."""
        ts = [self.trace["t"][i] for i in self.idx]
        j = bisect_left(ts, t)
        if j <= 0:
            return self.p[0]
        if j >= len(ts):
            return self.p[-1]
        t0, t1 = ts[j - 1], ts[j]
        return self.p[j - 1] + (self.p[j] - self.p[j - 1]) * ((t - t0) / (t1 - t0) if t1 > t0 else 0.0)

    def range(self, start: float, end: float) -> list[int]:
        a, b = bisect_left(self.p, start), bisect_left(self.p, end)
        return self.idx[a:b]


def analyse_corner(view: LapView, model: TrackModel, c: Corner, lead_m: float = 250.0) -> dict[str, Any]:
    tr = view.trace
    length = model.length_m or 1.0
    lead = lead_m / length
    entry_t, exit_t = view.time_at(c.entry), view.time_at(c.exit)
    inside = view.range(c.entry, c.exit) or [view.at(c.apex)]
    vmin_i = min(inside, key=lambda i: tr["speed"][i])

    # Braking point: where the last braking phase before the apex began.
    brake_p = None
    armed = True
    for i in view.range(max(0.0, c.entry - lead), c.apex):
        b = tr["brake"][i]
        if armed and b > 0.1:
            brake_p, armed = tr["p"][i], False
        elif b < 0.03:
            armed = True

    out: dict[str, Any] = {
        "corner": c.number,
        "time_s": round(exit_t - entry_t, 3),
        "min_speed_kmh": round(tr["speed"][vmin_i], 1),
        "min_speed_p": tr["p"][vmin_i],
        "apex_gear": int(tr["gear"][view.at(c.apex)]),
        "brake_p": brake_p,
        "coast_s": round(_coast_time(tr, view.range(max(0.0, c.entry - lead), c.exit)), 2),
    }
    if model.has_edges:
        for key, p in (("entry", c.entry), ("apex", c.apex), ("exit", c.exit)):
            i = view.at(p)
            _, off, frac = model.locate(tr["x"][i], tr["z"][i], model.index_at(tr["p"][i]))
            out[f"{key}_frac"] = round(frac, 3)  # 0 = left edge, 1 = right edge
            out[f"{key}_off_m"] = round(off, 2)
    return out


def _coast_time(tr: dict[str, list[float]], idx: list[int]) -> float:
    """Seconds with neither pedal pressed (above walking pace)."""
    total = 0.0
    for a, b in zip(idx, idx[1:], strict=False):
        if tr["gas"][a] < 0.05 and tr["brake"][a] < 0.05 and tr["speed"][a] > 30:
            total += max(0.0, tr["t"][b] - tr["t"][a])
    return total


def analyse_lap(trace: dict[str, list[float]], model: TrackModel) -> list[dict[str, Any]]:
    view = LapView(trace)
    if not view or not model.corners:
        return []
    return [analyse_corner(view, model, c) for c in model.corners]


# -- mastery across laps --------------------------------------------------------


def corner_mastery(history: list[list[dict[str, Any]]], recent: int = 10) -> dict[int, dict[str, Any]]:
    """Per corner: best and recent times, consistency and a green/amber/red grade.

    ``history`` is newest-first, one entry (list of corner dicts) per valid lap.
    """
    by_corner: dict[int, list[float]] = {}
    for lap in history:
        for c in lap:
            by_corner.setdefault(c["corner"], []).append(c["time_s"])
    out: dict[int, dict[str, Any]] = {}
    for num, times in by_corner.items():
        last = times[:recent]
        best = min(times)
        spread = statistics.pstdev(last) if len(last) > 1 else None
        median_gap = statistics.median(last) - best
        if len(last) < 3:
            grade = "new"
        elif spread is not None and spread <= 0.08 and median_gap <= 0.12:
            grade = "green"
        elif spread is not None and spread <= 0.2 and median_gap <= 0.3:
            grade = "amber"
        else:
            grade = "red"
        out[num] = {
            "corner": num,
            "best_s": round(best, 3),
            "median_s": round(statistics.median(last), 3),
            "spread_s": round(spread, 3) if spread is not None else None,
            "laps": len(times),
            "grade": grade,
        }
    return out


# -- track-width advice ---------------------------------------------------------


def width_advice(corner: Any, data: dict[str, Any], next_entry_gap_m: float | None) -> list[str]:
    """Plain-English notes on using the track width through one corner.

    Classic line: turn in from the outside, clip the inside at the apex, let the
    car run out to the outside on exit. ``frac`` is 0 at the left edge, 1 at the
    right edge. Exit advice is skipped when another corner follows immediately
    (chicanes, esses), where the exit is really the next entry.
    """
    if "apex_frac" not in data or getattr(corner, "grade", 1) >= 5:
        return []  # flat-out kinks: the "classic line" advice doesn't apply
    right = corner.direction == "R"
    outside = (lambda f: f) if right else (lambda f: 1 - f)  # 0 = at the outside edge
    inside = (lambda f: 1 - f) if right else (lambda f: f)  # 0 = at the inside edge
    side_out = "left" if right else "right"
    side_in = "right" if right else "left"
    tips: list[str] = []
    entry, apex, exit_ = outside(data["entry_frac"]), inside(data["apex_frac"]), outside(data["exit_frac"])
    if entry > 0.35:
        tips.append(
            f"Turn in from further {side_out}: you started the corner {pct(entry)} of the way across. "
            "A wider entry opens the corner up so you can carry more speed."
        )
    if apex > 0.3:
        tips.append(
            f"Get closer to the {side_in} at the apex ({pct(apex)} of the track away from it). "
            "Missing the apex makes the corner tighter and costs exit speed."
        )
    if (next_entry_gap_m is None or next_entry_gap_m > 80) and exit_ > 0.35:
        tips.append(
            f"Use all the road on exit: let the car run out to the {side_out} edge "
            f"(you finished {pct(exit_)} away from it). If you can't, you can get on the power earlier."
        )
    if data.get("coast_s", 0) > 0.4:
        tips.append(
            f"You coasted for {data['coast_s']:.1f} s here (no brake or throttle). "
            "Carry the brake into the turn-in or pick up the throttle sooner so the car stays balanced."
        )
    return tips


def pct(f: float) -> str:
    return f"{round(max(0.0, min(1.0, f)) * 100)}%"
