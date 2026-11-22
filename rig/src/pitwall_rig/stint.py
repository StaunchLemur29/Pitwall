"""The pit report: when you come into the pits, how the stint went.

Built from the laps of the stint (since you last left the pits) and their lap
reviews: times and consistency, the mistakes that kept happening (the same kind
at the same corner on more than one lap), what the stint did to the car, and
one thing to work on next.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any


def _fmt(ms: float) -> str:
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"


KIND_WORDS = {
    "off": "went off", "spin": "spun", "slide": "slid", "gear": "wrong gear",
    "throttle": "slow on the power", "slow": "lost time",
}


def stint_report(
    laps: list[dict[str, Any]],
    reviews: dict[int, dict[str, Any]],
    pb_ms: int | None,
    start: dict[str, Any] | None,
    now: dict[str, Any] | None,
    focus: dict[str, Any] | None,
    race: dict[str, Any] | None = None,
    laps_driven: float = 0.0,
    advice: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """``laps``: the stint's laps, oldest first (store summaries); ``reviews``: lap
    id -> lap review; ``start`` / ``now``: conditions at the start of the stint
    and now (fuel, tyre wear, damage); ``focus``: the coach's focus corner."""
    if not laps:
        return None
    clean = [x for x in laps if x["valid"] and not x.get("rewound")]
    times = sorted(x["lap_time_ms"] for x in clean)
    out: dict[str, Any] = {
        "laps": len([x for x in laps if not x.get("unfinished")]),
        "clean_laps": len(clean),
        "best": _fmt(times[0]) if times else None,
        "typical": _fmt(statistics.median(times)) if times else None,
        "spread_s": round(statistics.pstdev(times) / 1000, 2) if len(times) > 1 else None,
        "new_pb": bool(times and pb_ms and times[0] <= pb_ms),
    }

    # The mistakes that kept happening: same corner, same kind, on 2+ laps.
    seen: dict[tuple[str, str], list[float]] = defaultdict(list)
    kinds: Counter[str] = Counter()
    for x in laps:
        for w in (reviews.get(x["id"]) or {}).get("wrong", []):
            seen[(w["label"], w["kind"])].append(w.get("lost_s") or 0.0)
            kinds[w["kind"]] += 1
    repeats = sorted(((lbl, k, v) for (lbl, k), v in seen.items() if len(v) >= 2),
                     key=lambda r: (-len(r[2]), -sum(r[2])))
    out["repeats"] = [
        {"label": lbl, "kind": k, "laps": len(v), "lost_s": round(sum(v), 1),
         "text": f"{lbl}: {KIND_WORDS.get(k, k)} on {len(v)} laps" + (f", {sum(v):.1f} s in all" if sum(v) > 0.05 else "")}
        for lbl, k, v in repeats[:3]
    ]
    out["counts"] = {k: n for k, n in kinds.items() if k in ("off", "spin", "slide")}
    # The worst moments of the stint, repeated or not (offs, spins and slides first).
    worst = [w for x in laps for w in (reviews.get(x["id"]) or {}).get("wrong", [])]
    worst.sort(key=lambda w: (w["kind"] not in ("off", "spin", "slide"), -(w.get("lost_s") or 0)))
    out["worst"] = [{"label": w["label"], "kind": w["kind"], "text": w["text"]} for w in worst[:3]]

    # What the stint did to the car.
    car: list[str] = []
    if start and now:
        used = (start.get("fuel_l") or 0) - (now.get("fuel_l") or 0)
        n = laps_driven if laps_driven >= 0.5 else max(1, out["laps"])  # by distance: part laps count
        if used > 0.2:
            per = used / n
            car.append(f"Fuel: {per:.1f} L a lap, {now['fuel_l']:.0f} L left (about {now['fuel_l'] / per:.0f} laps).")
        if now.get("tyre_wear_pct") is not None and now["tyre_wear_pct"] >= 0.5:
            car.append(f"Tyres: {now['tyre_wear_pct']:.1f}% worn this stint.")
        if now.get("damage") is not None and now["damage"] >= 0.5:
            car.append("Damage: the car is damaged; repair it before comparing laps.")
    out["car"] = car

    # One thing for the next stint: the worst repeat, else the coach's focus.
    if repeats:
        lbl, k, _ = repeats[0]
        out["next"] = f"{lbl}: it {KIND_WORDS.get(k, k).replace('wrong gear', 'was the wrong gear')} more than once. Work on that first."
    elif focus:
        out["next"] = f"{focus['label']}: {focus.get('fix') or focus.get('why') or 'the most time to gain'}."
    else:
        out["next"] = None
    # Settings worth changing while you're stopped (advisor.py): the top two.
    out["setup"] = [{"title": a["title"], "do": a["do"], "why": a["why"]} for a in (advice or [])[:2]]
    if race:
        out["race"] = race
    return out
