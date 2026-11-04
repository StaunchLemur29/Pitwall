"""Hardware checks from your laps: force feedback clipping (TS-PC) and how you
use the brake pedal (T-LCM). Plain numbers and one suggestion each."""

from __future__ import annotations

import statistics
from typing import Any

from .analysis import LapView

CLIP = 0.98  # |force feedback| at or above this is clipping (AC caps it at 1)


def ffb_report(traces: list[dict[str, list[float]]], model: Any = None) -> dict[str, Any] | None:
    """How much of your driving the force feedback was maxed out, and where."""
    laps = [t for t in traces if t.get("ffb") and max(t["ffb"]) > 0]
    if not laps:
        return None
    per_lap, peaks, where = [], [], {}
    for tr in laps:
        on = [i for i, s in enumerate(tr["speed"]) if s > 20]
        if not on:
            continue
        clipped = [i for i in on if tr["ffb"][i] >= CLIP]
        per_lap.append(100.0 * len(clipped) / len(on))
        peaks.append(max(tr["ffb"][i] for i in on))
        if model is not None and getattr(model, "corners", None):
            for i in clipped:
                p = tr["p"][i]
                c = next((c for c in model.corners if c.entry <= p <= c.exit), None)
                if c is not None:
                    where[c.label] = where.get(c.label, 0) + 1
    if not per_lap:
        return None
    pct = statistics.median(per_lap)
    if pct >= 8:
        advice, cut = "Clipping a lot: lower this car's FFB gain by about 20 to 25 %. You'll feel more of the grip.", 22
    elif pct >= 2:
        advice, cut = "Some clipping in the hardest corners: lower this car's FFB gain by about 10 %.", 10
    elif statistics.median(peaks) < 0.6:
        advice, cut = "Lots of headroom: you could raise this car's FFB gain by about 15 % for more detail.", -15
    else:
        advice, cut = "Fine: barely any clipping.", 0
    return {
        "laps": len(per_lap),
        "clipping_pct": round(pct, 1),
        "peak": round(statistics.median(peaks), 2),
        "worst_corners": [k for k, _ in sorted(where.items(), key=lambda kv: -kv[1])[:3]],
        "gain_change_pct": -cut,
        "advice": advice,
    }


def brake_stops(tr: dict[str, list[float]]) -> list[dict[str, float]]:
    """Each time you braked: how hard (peak 0..1), how long it took to get
    there, and how long you took to let go (from the last moment near the peak)."""
    idx = LapView(tr).idx if tr.get("p") else list(range(len(tr["t"])))
    b, t = tr["brake"], tr["t"]
    stops: list[dict[str, float]] = []
    cur: list[tuple[float, float]] = []

    def close() -> None:
        if len(cur) > 1 and cur[-1][0] - cur[0][0] >= 0.3:
            peak = max(v for _, v in cur)
            near = [ts for ts, v in cur if v >= 0.9 * peak]
            stops.append({"peak": peak, "apply_s": near[0] - cur[0][0], "release_s": cur[-1][0] - near[-1]})

    for i in idx:
        if b[i] > 0.05:
            cur.append((t[i], b[i]))
        elif cur:
            close()
            cur = []
    close()
    return stops


def pedal_report(traces: list[dict[str, list[float]]]) -> dict[str, Any] | None:
    stops = [s for tr in traces if tr.get("brake") for s in brake_stops(tr)]
    if len(stops) < 8:
        return None
    peaks = [s["peak"] for s in stops]
    full = sum(1 for p in peaks if p >= 0.95) / len(stops)
    spread = statistics.pstdev(peaks)
    abrupt = sum(1 for s in stops if s["release_s"] < 0.15) / len(stops)
    notes = []
    if full >= 0.4:
        notes.append("You hit 100 % brake on most stops: you may be pressing past the pedal's range. Raise the T-LCM's "
                     "maximum force in Thrustmaster's software so full braking needs more pressure: finer control.")
    elif full < 0.1 and statistics.median(peaks) < 0.85:
        notes.append("You rarely use full brake. If you're pressing hard and still not reaching 100 %, lower the "
                     "T-LCM's maximum force; if not, there's braking left on the table.")
    if spread > 0.12:
        notes.append("How hard you brake varies a lot from stop to stop: practise hitting the same peak (drills help).")
    if abrupt > 0.3:
        notes.append("You often let go of the brake suddenly: ease off more gradually as you turn in (trail braking).")
    if not notes:
        notes.append("Good: consistent peaks and smooth releases.")
    return {
        "stops": len(stops),
        "peak_median": round(statistics.median(peaks), 2),
        "peak_spread": round(spread, 2),
        "full_pct": round(full * 100),
        "release_s_median": round(statistics.median(s["release_s"] for s in stops), 2),
        "abrupt_pct": round(abrupt * 100),
        "notes": notes,
    }
