"""Live tips: at most one per lap, on the straight before the corner it's about.

What to say comes from what keeps going wrong this session (the same kind of
mistake at the same corner on two or more of your last few laps), else the
session's focus corner and its fix. When to say it: approaching that corner on
the straight before it (no other corner in between), never mid-corner, once a
lap, and not while a drill, cold tyres or a crash notice has the coach strip.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from collections.abc import Callable
from typing import Any

RECENT_LAPS = 4
SHOW_FROM_M = 600.0  # start showing this far before the corner's entry...
SHOW_UNTIL_M = 150.0  # ...if you're at least this far away (time to read it)
HIDE_AT_M = 20.0  # gone as you get to the corner
MAX_S = 10.0


KIND_WORDS = {"off": "went off", "spin": "spun", "slide": "slid", "gear": "wrong gear",
              "throttle": "slow on the power", "slow": "lost time"}


_RULES = [
    (re.compile(r"(\d+) km/h slower at the slowest point"), lambda m: f"Carry {m[1]} km/h more to the apex."),
    (re.compile(r"(\d+) km/h slower on the exit"), lambda m: f"Get {m[1]} km/h more on the exit: on the power earlier and straighter."),
    (re.compile(r"Braked (\d+) m earlier"), lambda m: f"Brake {m[1]} m later."),
    (re.compile(r"Back to full throttle (\d+) m later"), lambda m: f"Full throttle {m[1]} m sooner."),
    (re.compile(r"Coasted ([\d.]+) s longer"), lambda m: "Don't coast: straight from the brake onto the throttle."),
    (re.compile(r"Gear (\d+) at the apex; .* used (\d+)"), lambda m: f"Use gear {m[2]} at the apex, not {m[1]}."),
    (re.compile(r"You braked here; .* didn't"), lambda m: "Try it without braking: a lift should do."),
]


def as_instruction(note: str | None) -> str | None:
    """A difference from a faster lap (analysis.compare_notes) as something to
    do, or None if it isn't a loss (quicker somewhere, braked later...)."""
    if not note:
        return None
    for rx, fn in _RULES:
        m = rx.search(note)
        if m:
            return fn(m)
    return None


def _first_sentence(text: str) -> str:
    cut = text.find(". ")
    return text if cut < 0 else text[: cut + 1]


class Tips:
    def __init__(self) -> None:
        self._recent: deque[list[dict[str, Any]]] = deque(maxlen=RECENT_LAPS)
        self.showing: dict[str, Any] | None = None  # {corner, label, text, kind, since}
        self._shown_lap: int | None = None

    def reset(self) -> None:
        self._recent.clear()
        self.showing, self._shown_lap = None, None

    def add_lap(self, wrong: list[dict[str, Any]]) -> None:
        """A finished lap's review ("where it went wrong")."""
        self._recent.append([w for w in wrong if w.get("corner") is not None])

    def pick(self, focus: dict[str, Any] | None) -> dict[str, Any] | None:
        """The tip worth giving now: a repeated mistake, else the focus."""
        seen: Counter[tuple[int, str]] = Counter()
        latest: dict[tuple[int, str], dict[str, Any]] = {}
        for lap in self._recent:  # oldest first, so ``latest`` ends with the newest
            for k in {(w["corner"], w["kind"]) for w in lap}:
                seen[k] += 1
            for w in lap:
                latest[(w["corner"], w["kind"])] = w
        n_laps = len(self._recent)
        repeats = [(n, k) for k, n in seen.items() if n >= 2]
        if repeats:
            n, k = max(repeats, key=lambda r: (r[0], r[1][1] in ("slide", "spin", "off")))
            w = latest[k]
            if k[1] == "off":
                text = f"You've gone off here on {n} of your last {n_laps} laps. Leave a little more margin."
            else:
                text = f"{_first_sentence(w['text'])} ({n} of your last {n_laps} laps.)"
            return {"corner": k[0], "label": w["label"], "kind": k[1], "text": text}
        # The same corner going wrong in different ways: a trouble spot.
        by_corner: Counter[int] = Counter()
        kinds: dict[int, set[str]] = {}
        for lap in self._recent:
            for c in {w["corner"] for w in lap}:
                by_corner[c] += 1
            for w in lap:
                kinds.setdefault(w["corner"], set()).add(KIND_WORDS.get(w["kind"], w["kind"]))
        spots = [(n, c) for c, n in by_corner.items() if n >= 2]
        if spots:
            n, c = max(spots)
            w = next(w for lap in reversed(self._recent) for w in lap if w["corner"] == c)
            return {"corner": c, "label": w["label"], "kind": "trouble",
                    "text": f"Trouble here on {n} of your last {n_laps} laps ({', '.join(sorted(kinds[c]))}). "
                            "Take it a touch easier until it's clean."}
        if focus and focus.get("fix"):
            return {"corner": focus["corner"], "label": focus["label"], "kind": "focus", "text": focus["fix"]}
        return None

    def live(self, lap: int, next_corner: int | None, dist_m: float | None, now: float,
             focus: dict[str, Any] | None, quiet: bool,
             approach: Callable[[int], int] = lambda c: c) -> dict[str, Any] | None:
        """The tip to show this frame, if any. ``quiet``: something else has the
        coach strip (a drill, cold tyres, a notice). ``approach``: the corner whose
        straight leads to this one (the first of a run of linked corners), where
        the tip is given."""
        s = self.showing
        if s is not None:
            if quiet or next_corner != s["at"] or dist_m is None or dist_m < HIDE_AT_M or now - s["since"] > MAX_S:
                self.showing = None
            return {k: v for k, v in self.showing.items() if k not in ("since", "at")} if self.showing else None
        if quiet or self._shown_lap == lap or dist_m is None or not (SHOW_UNTIL_M <= dist_m <= SHOW_FROM_M):
            return None
        tip = self.pick(focus)
        if tip is None or approach(tip["corner"]) != next_corner:
            return None
        self.showing, self._shown_lap = {**tip, "since": now, "at": next_corner}, lap
        return tip
