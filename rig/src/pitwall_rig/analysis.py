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


def analyse_corner(
    view: LapView, model: TrackModel, c: Corner, lead_m: float = 250.0, prev_apex: float | None = None
) -> dict[str, Any]:
    tr = view.trace
    length = model.length_m or 1.0
    lead = lead_m / length
    # Braking for the corner before (a chicane's first half) isn't braking for this one.
    look_from = max(0.0, c.entry - lead)
    if prev_apex is not None and look_from < prev_apex < c.entry:
        look_from = prev_apex
    entry_t, exit_t = view.time_at(c.entry), view.time_at(c.exit)
    inside = view.range(c.entry, c.exit) or [view.at(c.apex)]
    vmin_i = min(inside, key=lambda i: tr["speed"][i])

    # Braking point: where the last braking phase before the apex began. A short
    # release (a lift, modulating the pedal) doesn't start a new phase: you have
    # to be off the brake for 40 m before a later press counts as fresh braking.
    brake_p = None
    released_at = None  # progress where the brake was last let go
    for i in view.range(look_from, c.apex):
        b, p = tr["brake"][i], tr["p"][i]
        if b > 0.1:
            if brake_p is None or (released_at is not None and (p - released_at) * length > 40):
                brake_p = p
            released_at = None
        elif b < 0.03 and released_at is None and brake_p is not None:
            released_at = p

    # Speeds at the key moments, and where the throttle went back to full.
    brake_i = view.at(brake_p) if brake_p is not None else None
    exit_i = view.at(c.exit)
    throttle_p = None
    for i in view.range(tr["p"][vmin_i], min(0.99999, c.exit + 150 / length)):
        if tr["gas"][i] >= 0.9:
            throttle_p = tr["p"][i]
            break
    peak_brake = max((tr["brake"][i] for i in view.range(look_from, c.exit)), default=0.0)

    out: dict[str, Any] = {
        "corner": c.number,
        # metres before the apex you started braking (None: didn't brake)
        "brake_m": round((c.apex - brake_p) * length) if brake_p is not None else None,
        "peak_brake": round(peak_brake, 2),
        "entry_kmh": round(tr["speed"][brake_i if brake_i is not None else view.at(c.entry)], 1),
        "exit_kmh": round(tr["speed"][exit_i], 1),
        # metres after the apex you were back to full throttle (negative: before it)
        "throttle_m": round((throttle_p - c.apex) * length) if throttle_p is not None else None,
        "time_s": round(exit_t - entry_t, 3),
        "min_speed_kmh": round(tr["speed"][vmin_i], 1),
        "min_speed_p": tr["p"][vmin_i],
        "apex_gear": int(tr["gear"][view.at(c.apex)]),
        "brake_p": brake_p,
        "coast_s": round(_coast_time(tr, view.range(look_from, c.exit)), 2),
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
    cs = model.corners
    return [analyse_corner(view, model, c, prev_apex=cs[i - 1].apex if i > 0 else None) for i, c in enumerate(cs)]


def compare_notes(mine: dict[str, Any], other: dict[str, Any], label: str) -> list[str]:
    """What you did differently from another lap through one corner, biggest
    likely cause first, in plain words."""
    notes: list[tuple[float, str]] = []  # (weight, text)
    dv = mine["min_speed_kmh"] - other["min_speed_kmh"]
    if abs(dv) >= 3:
        notes.append((abs(dv) * 1.5, f"{abs(dv):.0f} km/h {'slower' if dv < 0 else 'faster'} at the slowest point than {label}."))
    de = mine.get("exit_kmh", 0) - other.get("exit_kmh", 0)
    if abs(de) >= 3 and mine.get("exit_kmh") is not None and other.get("exit_kmh") is not None:
        notes.append((abs(de) * 1.2, f"{abs(de):.0f} km/h {'slower' if de < 0 else 'faster'} on the exit than {label}."))
    mb, ob = mine.get("brake_m"), other.get("brake_m")
    if mb is not None and ob is not None and abs(mb - ob) >= 8:
        d = mb - ob
        notes.append((abs(d) / 3, f"Braked {abs(d)} m {'earlier' if d > 0 else 'later'} than {label}."))
    elif mb is not None and ob is None:
        notes.append((5, f"You braked here; {label} didn't."))
    elif mb is None and ob is not None:
        notes.append((5, f"You didn't brake here; {label} did."))
    mt, ot = mine.get("throttle_m"), other.get("throttle_m")
    if mt is not None and ot is not None and abs(mt - ot) >= 10:
        d = mt - ot
        notes.append((abs(d) / 4, f"Back to full throttle {abs(d)} m {'later' if d > 0 else 'earlier'} than {label}."))
    dc = mine.get("coast_s", 0) - other.get("coast_s", 0)
    if dc >= 0.3:
        notes.append((dc * 10, f"Coasted {dc:.1f} s longer than {label} (no brake, no throttle)."))
    if mine.get("apex_gear") and other.get("apex_gear") and mine["apex_gear"] != other["apex_gear"]:
        notes.append((2, f"Gear {mine['apex_gear']} at the apex; {label} used {other['apex_gear']}."))
    return [t for _, t in sorted(notes, key=lambda n: -n[0])]


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


def line_vs_optimal(corner: Any, data: dict[str, Any], model: TrackModel) -> dict[str, float] | None:
    """How far you were from the optimal line at turn-in, apex and exit, in
    metres towards the inside of the corner (negative = wider than it).
    None if the track has no optimal line (yet) or the lap has no positions."""
    out = {}
    for key, p in (("entry", corner.entry), ("apex", corner.apex), ("exit", corner.exit)):
        mine = data.get(f"{key}_off_m")  # metres left of the AI line
        opt = model.optimal_at(p)
        if mine is None or opt is None:
            return None
        towards_left = mine - opt
        out[key] = round(towards_left if corner.direction == "L" else -towards_left, 1)
    return out


# Closer to the optimal line than this counts as on it (a car is ~2 m wide).
LINE_TOLERANCE_M = 1.5


def width_advice(corner: Any, data: dict[str, Any], next_entry_gap_m: float | None) -> list[str]:
    """Plain-English notes on using the track width through one corner.

    Against the optimal line (``data["line"]``, from ``line_vs_optimal``) when
    the track has one: that's right for chicanes and linked corners too.
    Otherwise the classic rule of thumb: turn in from the outside, clip the
    inside at the apex, run out to the outside on exit (``frac`` is 0 at the
    left edge, 1 at the right edge). Exit advice is skipped when another corner
    follows immediately (chicanes, esses), where the exit is really the next entry.
    """
    if "apex_frac" not in data or getattr(corner, "grade", 1) >= 5:
        return []  # flat-out kinks: line advice isn't worth the distraction
    right = corner.direction == "R"
    side_out = "left" if right else "right"
    side_in = "right" if right else "left"
    check_exit = next_entry_gap_m is None or next_entry_gap_m > 80
    line = data.get("line")
    tips: list[str] = []
    if line:
        tol = LINE_TOLERANCE_M
        if line["entry"] > tol:
            tips.append(
                f"Turn in from further {side_out}: the optimal line starts this corner "
                f"{line['entry']:.1f} m wider than you did, which opens it up."
            )
        if line["apex"] < -tol:
            tips.append(
                f"Get closer to the {side_in} at the apex: the optimal line is {-line['apex']:.1f} m nearer it. "
                "Missing the apex makes the corner tighter and costs exit speed."
            )
        elif line["apex"] > tol:
            tips.append(
                f"You were {line['apex']:.1f} m inside the optimal line at the apex: usually a sign of turning in "
                "too early, which pinches the exit."
            )
        if check_exit and line["exit"] > tol:
            tips.append(
                f"Use more road on exit: the optimal line runs {line['exit']:.1f} m further {side_out}. "
                "If you don't need it, you can get on the power earlier."
            )
    else:
        outside = (lambda f: f) if right else (lambda f: 1 - f)  # 0 = at the outside edge
        inside = (lambda f: 1 - f) if right else (lambda f: f)  # 0 = at the inside edge
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
        if check_exit and exit_ > 0.35:
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


# -- car systems: battery and DRS along the lap ---------------------------------

DRS_MISSED_M = 150.0  # flat out, DRS available, not opened for this long = worth a note
BATTERY_EMPTY_M = 80.0  # wanting power with an empty battery for this long
EMPTY = 0.02


def _runs(trace: dict[str, list[float]], idx: list[int], length_m: float, inside) -> list[tuple[int, int, float]]:
    """Stretches (first index, last index, metres) where ``inside(i)`` holds."""
    out: list[tuple[int, int, float]] = []
    start, metres = None, 0.0
    for a, b in zip(idx, idx[1:], strict=False):
        if inside(a):
            if start is None:
                start, metres = a, 0.0
            metres += max(0.0, trace["p"][b] - trace["p"][a]) * length_m
        elif start is not None:
            out.append((start, a, metres))
            start = None
    if start is not None:
        out.append((start, idx[-1], metres))
    return out


def _before(model: TrackModel, p: float) -> str:
    nxt = model.next_corner(p)
    return f"before {nxt[0].label}" if nxt else ""


def analyse_systems(trace: dict[str, list[float]], model: TrackModel, profile: dict[str, Any] | None) -> dict[str, Any]:
    """Battery and DRS use on one lap, with plain-English notes. Only for
    systems the car has (``profile``) and the trace recorded."""
    out: dict[str, Any] = {"drs": None, "battery": None, "notes": []}
    view = LapView(trace)
    if not view or not profile:
        return out
    idx, L = view.idx, model.length_m or 1.0
    tr = trace

    if profile.get("drs") and "drs" in tr and any(v >= 1 for v in tr["drs"]):
        open_m = sum(m for _, _, m in _runs(tr, idx, L, lambda i: tr["drs"][i] >= 2))
        missed = []
        for a, b, m in _runs(tr, idx, L, lambda i: tr["drs"][i] == 1 and tr["gas"][i] >= 0.95):
            if m >= DRS_MISSED_M:
                missed.append({"start_p": tr["p"][a], "end_p": tr["p"][b], "metres": round(m), "near": _before(model, tr["p"][b])})
        out["drs"] = {"open_m": round(open_m), "missed": missed}
        for x in missed:
            out["notes"].append(f"DRS was available but not opened for {x['metres']} m {x['near']}.".replace("  ", " "))

    if profile.get("battery") and "batt" in tr and max(tr["batt"][i] for i in idx) > 0:
        empty = []
        for a, b, m in _runs(tr, idx, L, lambda i: tr["batt"][i] <= EMPTY and tr["gas"][i] >= 0.9):
            if m >= BATTERY_EMPTY_M:
                empty.append({"start_p": tr["p"][a], "end_p": tr["p"][b], "metres": round(m), "near": _before(model, tr["p"][b])})
        start, end = tr["batt"][idx[0]], tr["batt"][idx[-1]]
        out["battery"] = {
            "start": round(start, 3),
            "end": round(end, 3),
            "min": round(min(tr["batt"][i] for i in idx), 3),
            "empty": empty,
        }
        for x in empty:
            out["notes"].append(
                f"Battery ran out for {x['metres']} m {x['near']}: nothing left to deploy there.".replace("  ", " ")
            )
        if not empty and end >= 0.5 and start - end < 0.1:
            out["notes"].append(f"Finished the lap with {round(end * 100)}% battery: there's energy left to deploy.")
    return out
