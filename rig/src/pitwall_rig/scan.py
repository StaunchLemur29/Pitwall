"""Blind-spot scan: fundamentals your telemetry shows you keep missing.

Not one lap's mistakes (the lap review does that) but habits across your
recent laps on a car + track: coasting into corners, braking earlier than the
optimal run, late back to full throttle, a different gear from the optimal
run's, an abrupt brake release, corners you can't repeat. Each finding says
how often, where it shows most, why it matters, and the drill to fix it (the
practice section with the worst corner).

Silent until there's enough to go on (MIN_PASSES per corner), and only what's
clearly a habit (a share of corner passes, not one-offs).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

MIN_PASSES = 6  # corner passes needed before a habit at that corner counts
HABIT = 0.4  # this share of your passes through a corner


def _worst(per_corner: dict[int, list[float]], labels: dict[int, str], n: int = 3) -> list[int]:
    return [c for c, _ in sorted(per_corner.items(), key=lambda kv: -statistics.mean(kv[1]))[:n]]


def blind_spots(
    laps: list[list[dict[str, Any]]],
    corners: list[Any],
    opt_rows: dict[int, dict[str, Any]] | None,
    pedals: dict[str, Any] | None,
    practice: list[Any],
    mastery: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """``laps``: your recent laps' corners (the ones that count: driven, clean),
    newest first. ``opt_rows``: the optimal run per corner. Returns findings,
    most important first."""
    labels = {c.number: c.label for c in corners}
    grade = {c.number: getattr(c, "grade", 3) for c in corners}
    passes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for lap in laps:
        for c in lap:
            passes[c["corner"]].append(c)
    enough = {num: ps for num, ps in passes.items() if len(ps) >= MIN_PASSES and grade.get(num, 3) < 5}
    out: list[dict[str, Any]] = []

    def section_for(num: int) -> dict[str, Any] | None:
        ps = next((p for p in practice if num in getattr(p, "corners", [])), None)
        return {"number": ps.number, "name": ps.name} if ps else None

    def add(key: str, title: str, hits: dict[int, list[float]], share: float, detail: str, why: str, weight: float) -> None:
        worst = _worst(hits, labels)
        out.append({
            "key": key, "title": title, "share": round(share, 2), "weight": round(weight, 2),
            "corners": [labels.get(c, f"Corner {c}") for c in worst],
            "detail": detail, "why": why,
            "drill": section_for(worst[0]) if worst else None,
        })

    def habit(test, value) -> tuple[dict[int, list[float]], float]:
        """Corners where ``test(pass)`` holds on HABIT+ of passes, the values there,
        and the share of all passes (over the corners with enough laps)."""
        hits: dict[int, list[float]] = {}
        total = n_hit = 0
        for num, ps in enough.items():
            mine = [p for p in ps if test(num, p)]
            total += len(ps)
            n_hit += len(mine)
            if len(mine) >= HABIT * len(ps):
                hits[num] = [value(num, p) for p in mine]
        return hits, (n_hit / total if total else 0.0)

    # Coasting: neither brake nor throttle into the corner.
    hits, share = habit(lambda n, p: (p.get("coast_s") or 0) >= 0.3, lambda n, p: p["coast_s"])
    if len(hits) >= 2:
        avg = statistics.mean(v for vs in hits.values() for v in vs)
        add("coasting", "You coast into corners", hits, share,
            f"About {avg:.1f} s with neither brake nor throttle, on {share:.0%} of corners.",
            "Coasting is time spent not slowing down and not speeding up. Go straight from the brake to the throttle "
            "(a little throttle to balance the car is fine).", share * 2 + avg)

    if opt_rows:
        # Braking earlier than the optimal run.
        def early(n, p):
            o = opt_rows.get(n)
            return o is not None and p.get("brake_m") is not None and o.get("brake_m") is not None and p["brake_m"] - o["brake_m"] >= 15
        hits, share = habit(early, lambda n, p: p["brake_m"] - opt_rows[n]["brake_m"])
        if len(hits) >= 2:
            avg = statistics.mean(v for vs in hits.values() for v in vs)
            add("brake_early", "You brake early", hits, share,
                f"About {avg:.0f} m before the optimal run's braking point, on {share:.0%} of braking corners.",
                "Braking later is the cheapest time there is. Move one braking point a few metres at a time, "
                "and brake harder at the start.", share * 2 + avg / 20)

        # Late back to full throttle.
        def late(n, p):
            o = opt_rows.get(n)
            return o is not None and p.get("throttle_m") is not None and o.get("throttle_m") is not None and p["throttle_m"] - o["throttle_m"] >= 20
        hits, share = habit(late, lambda n, p: p["throttle_m"] - opt_rows[n]["throttle_m"])
        if len(hits) >= 2:
            avg = statistics.mean(v for vs in hits.values() for v in vs)
            add("throttle_late", "You're late back on the power", hits, share,
                f"Full throttle about {avg:.0f} m later than the optimal run, on {share:.0%} of corners.",
                "Exit speed carries all the way down the next straight. Aim for an earlier apex and a straighter exit "
                "so you can feed the throttle in sooner.", share * 2 + avg / 25)

        # A different gear from the optimal run's.
        def gear(n, p):
            o = opt_rows.get(n)
            return o is not None and p.get("apex_gear") and o.get("apex_gear") and p["apex_gear"] != o["apex_gear"]
        hits, share = habit(gear, lambda n, p: abs(p["apex_gear"] - opt_rows[n]["apex_gear"]))
        if len(hits) >= 2:
            add("gears", "Gear choice", hits, share,
                f"A different gear at the apex from the optimal run's on {share:.0%} of corners.",
                "Too high bogs the exit; too low and the rear steps out. Try the optimal run's gear for a few laps "
                "in the corners listed.", share * 1.5)

    # Brake release: let go abruptly instead of easing off into the corner.
    if pedals and pedals.get("abrupt_pct", 0) >= 40 and len(laps) >= MIN_PASSES:
        out.append({
            "key": "brake_release", "title": "You let go of the brake abruptly",
            "share": round(pedals["abrupt_pct"] / 100, 2), "weight": pedals["abrupt_pct"] / 50, "corners": [],
            "detail": f"{pedals['abrupt_pct']}% of stops end in under 0.15 s.",
            "why": "Easing off the brake as you turn in (trail braking) keeps weight on the front so the car turns. "
                   "Dropping it suddenly makes it run wide.",
            "drill": None,
        })

    # Corners you can't repeat (red on the mastery grades).
    if mastery:
        red = {n: [m.get("spread_s") or 0.0] for n, m in mastery.items() if m.get("grade") == "red" and (m.get("laps") or 0) >= MIN_PASSES}
        if len(red) >= 2:
            add("consistency", "Corners you can't repeat yet", red, len(red) / max(1, len(mastery)),
                f"{len(red)} corners vary by more than 0.2 s from lap to lap.",
                "Consistency comes before speed: drive these at 9/10 until they're the same every lap, then push.",
                len(red) / max(1, len(mastery)) * 2)

    out.sort(key=lambda f: -f["weight"])
    return out
