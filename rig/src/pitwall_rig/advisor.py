"""Electronics and tyre-pressure advisor: what your laps say about brake bias,
ABS, TC and tyre pressures. Suggestions only: Pitwall never changes the car.

Per frame it watches each wheel against the car's speed:

- a **lock-up**: braking, and a wheel turning much slower than the car is
  going (fronts or rears, told apart: they call for opposite changes);
- **wheelspin**: on the throttle, and a wheel turning much faster;
- how much of your braking the **ABS** is working, and how much of your
  flat-out driving the **TC** is cutting;
- **hot tyre pressures**, averaged over the lap once the car's up to speed.

Each lap's findings are kept with the lap. Advice comes from your recent laps
*on the current settings* (the same brake bias, ABS and TC): change one and
the advice starts again from what the new setting does.

Wheel speeds come from the game in turns per second, so the rolling radius of
each wheel is learnt as you drive (rolling freely in a straight line), which
works for any car, mods included.
"""

from __future__ import annotations

import statistics
from collections import Counter, deque
from collections.abc import Callable
from typing import Any

from .models import Frame, GameStatus

LOCK = -0.25  # a wheel this much slower than the car while braking is locking
SPIN = 0.20  # this much faster on the throttle is spinning
LOCK_MIN_S = 0.15
SPIN_MIN_S = 0.25
MIN_KMH = 50.0  # below this slip is all noise (and a locked wheel at walking pace doesn't matter)
MIN_LAPS = 3  # laps on the current settings before there's advice
RECENT = 8  # laps looked at
AXLE_PSI = 1.0  # left / right hot-pressure difference worth evening out
TARGET_PSI = 0.7  # this far from the car's ideal hot pressure is worth changing

WHEELS = ("front left", "front right", "rear left", "rear right")


class Advisor:
    """Feed it live frames; ``end_lap`` gives the lap's findings."""

    def __init__(self) -> None:
        self._ratio: list[deque[float]] = [deque(maxlen=300) for _ in range(4)]  # v / wheel speed, rolling freely
        self._radius: list[float] | None = None
        self._last: Frame | None = None
        self._run: dict[str, dict[str, Any]] = {}  # kind -> the event under way {t0, p, worst}
        self.reset_lap()

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def reset_lap(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._psi = [0.0, 0.0, 0.0, 0.0]
        self._psi_n = 0
        self._brake_s = self._abs_s = self._power_s = self._tc_s = 0.0
        self._run = {}

    # -- live ---------------------------------------------------------------------

    def slip(self, f: Frame) -> list[float] | None:
        """Each wheel against the car's speed: -1 = locked, 0 = rolling, +0.2 = 20 % faster."""
        if self._radius is None or not f.wheel_speed or f.speed_kmh < MIN_KMH:
            return None
        v = f.speed_kmh / 3.6
        return [(abs(w) * r - v) / v for w, r in zip(f.wheel_speed, self._radius, strict=True)]

    def feed(self, f: Frame) -> None:
        prev, self._last = self._last, f
        if f.status != GameStatus.LIVE or f.in_pit_lane or f.in_pit_box or prev is None or f.packet_id == prev.packet_id:
            return
        dt = min(0.1, max(0.0, f.t - prev.t))
        ws = f.wheel_speed
        # Rolling freely in a straight line: that's what one turn of each wheel covers.
        if (ws and len(ws) == 4 and f.brake < 0.02 and 0.05 < f.gas < 0.7 and f.speed_kmh > 60 and abs(f.steer) < 0.15
                and all(abs(w) > 1 for w in ws)):
            v = f.speed_kmh / 3.6
            for q, w in zip(self._ratio, ws, strict=True):
                q.append(v / abs(w))
            if len(self._ratio[0]) >= 60:
                self._radius = [statistics.median(q) for q in self._ratio]
        s = self.slip(f)
        braking, power = f.brake > 0.2, f.gas > 0.5 and f.brake < 0.05
        if f.speed_kmh >= MIN_KMH:
            if braking:
                self._brake_s += dt
                if (f.abs or 0) > 0:
                    self._abs_s += dt
            if f.gas > 0.9 and f.brake < 0.05 and f.speed_kmh < 220:
                self._power_s += dt
                if (f.tc or 0) > 0:
                    self._tc_s += dt
            if f.tyre_pressure_psi and f.speed_kmh > 80:
                for i, p in enumerate(f.tyre_pressure_psi[:4]):
                    self._psi[i] += p
                self._psi_n += 1
        self._watch("lock_front", s is not None and braking and min(s[0], s[1]) < LOCK, f, LOCK_MIN_S,
                    -min(s[0], s[1]) if s else 0.0)
        self._watch("lock_rear", s is not None and braking and min(s[2], s[3]) < LOCK, f, LOCK_MIN_S,
                    -min(s[2], s[3]) if s else 0.0)
        self._watch("spin", s is not None and power and max(s) > SPIN, f, SPIN_MIN_S, max(s) if s else 0.0)

    def _watch(self, kind: str, on: bool, f: Frame, min_s: float, how: float) -> None:
        run = self._run.get(kind)
        if on:
            if run is None:
                self._run[kind] = {"t0": f.t, "p": f.lap_progress, "worst": how, "t1": f.t}
            else:
                run["worst"], run["t1"] = max(run["worst"], how), f.t
        elif run is not None:
            del self._run[kind]
            if run["t1"] - run["t0"] >= min_s:
                self._events.append({"kind": kind, "p": round(run["p"], 4), "s": round(run["t1"] - run["t0"], 2),
                                     "worst": round(min(1.0, run["worst"]), 2)})

    def end_lap(self, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """This lap's findings (None when there were no wheel speeds to go on),
        with the settings it was driven on."""
        out = None
        if self._radius is not None:
            out = {
                "events": self._events,
                "psi": [round(p / self._psi_n, 2) for p in self._psi] if self._psi_n > 200 else None,
                "abs_share": round(self._abs_s / self._brake_s, 2) if self._brake_s > 3 else None,
                "tc_share": round(self._tc_s / self._power_s, 2) if self._power_s > 3 else None,
                "settings": settings or {},
            }
        self.reset_lap()
        return out


# -- advice from recent laps --------------------------------------------------------


def same_settings(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    a, b = a or {}, b or {}
    if a.get("abs") != b.get("abs") or a.get("tc") != b.get("tc"):
        return False
    ba, bb = a.get("bb"), b.get("bb")
    return (ba is None and bb is None) or (ba is not None and bb is not None and abs(ba - bb) < 0.002)


def advise(
    laps: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    corner_at: Callable[[float], tuple[int, str] | None],
    target_psi: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """``laps``: each lap's findings (``Advisor.end_lap``), newest first.
    ``corner_at``: lap progress -> (corner number, label) of the corner there
    or coming up. ``target_psi``: the car's ideal hot pressure (front, rear), if
    known. Returns {"laps", "settings", "advice": [...], "psi"}; each piece of
    advice has a key, a title, what to do, the evidence, and (for a live tip)
    the corner it shows at most."""
    laps = [x for x in laps if x]
    if not laps:
        return {"laps": 0, "settings": None, "advice": [], "psi": None}
    now = laps[0].get("settings") or {}
    mine = []
    for x in laps:  # back to the last time a setting changed
        if not same_settings(x.get("settings"), now):
            break
        mine.append(x)
    mine = mine[:RECENT]
    p = profile or {}
    out: list[dict[str, Any]] = []

    def where(kind: str) -> tuple[int, int, list[tuple[int, str, int]]]:
        """Events of a kind: how many, on how many laps, and the corners (number, label, laps) worst first."""
        total, on_laps = 0, 0
        per: Counter[tuple[int, str]] = Counter()
        for x in mine:
            ev = [e for e in x["events"] if e["kind"] == kind]
            total += len(ev)
            on_laps += bool(ev)
            for c in {corner_at(e["p"]) for e in ev} - {None}:
                per[c] += 1  # type: ignore[index]
        return total, on_laps, [(c[0], c[1], n) for c, n in per.most_common(3)]

    def habit(total: int, on_laps: int, corners: list[tuple[int, str, int]]) -> bool:
        """Not a one-off: the same corner on two laps, or on half your laps or more."""
        return len(mine) >= MIN_LAPS and (bool(corners and corners[0][2] >= 2) or on_laps * 2 >= len(mine) >= 4)

    def places(corners: list[tuple[int, str, int]]) -> str:
        names = [c[1] for c in corners[:2]]
        return " and ".join(names) if names else "several places"

    def add(key: str, title: str, do: str, why: str, corners: list[tuple[int, str, int]], weight: float) -> None:
        out.append({"key": key, "title": title, "do": do, "why": why, "weight": round(weight, 2),
                    "corner": corners[0][0] if corners else None, "label": corners[0][1] if corners else None})

    n = len(mine)
    has_bias = bool(p.get("brake_bias")) or now.get("bb") is not None
    abs_on = bool(now.get("abs")) if "abs" in now else bool(p.get("abs"))
    tc_on = bool(now.get("tc")) if "tc" in now else bool(p.get("tc"))

    tf, lf, cf = where("lock_front")
    tr, lr, cr = where("lock_rear")
    if habit(tr, lr, cr) and tr >= tf:
        # Rears locking first makes the car want to swap ends: the one to fix first.
        add("lock_rear", "The rear wheels lock under braking",
            "Move the brake bias 1 % to the front." if has_bias else "Brake a little less hard, and downshift a touch later.",
            f"Rear lock-ups on {lr} of your last {n} laps, most at {places(cr)}. Locked rears make the car unstable "
            "into the corner. (Downshifting too early does it too.)", cr, 3 + lr / n)
    elif habit(tf, lf, cf):
        if p.get("abs") and not abs_on:
            do = "Turn the ABS on, or move the brake bias 1 % to the rear." if has_bias else "Turn the ABS on."
        elif has_bias and not abs_on:
            do = "Move the brake bias 1 % to the rear."
        elif abs_on:
            do = "Try one step more ABS." + (" Or move the brake bias 1 % to the rear." if has_bias else "")
        else:
            do = "Ease off the first hit of the brake a little there."
        add("lock_front", "The front wheels lock under braking", do,
            f"Front lock-ups on {lf} of your last {n} laps, most at {places(cf)}. A locked front doesn't steer "
            "and flat-spots the tyre.", cf, 2 + lf / n)

    ts, ls, cs = where("spin")
    if habit(ts, ls, cs):
        if p.get("tc") and not tc_on:
            do = "Turn the TC on, or squeeze the throttle on more gradually."
        elif tc_on:
            do = "Try one step more TC."
        else:
            do = "Squeeze the throttle on more gradually there."
        add("wheelspin", "Wheelspin on the way out", do,
            f"Wheelspin on {ls} of your last {n} laps, most out of {places(cs)}. Spinning wheels cost drive "
            "and cook the rear tyres.", cs, 1.5 + ls / n)

    if n >= MIN_LAPS and not any(a["key"] == "wheelspin" for a in out):
        shares = [x["tc_share"] for x in mine if x.get("tc_share") is not None]
        if tc_on and len(shares) >= MIN_LAPS and statistics.median(shares) >= 0.35:
            add("tc_busy", "The TC is cutting power a lot",
                "If the car feels planted on the way out, try one step less TC.",
                f"TC was working for {statistics.median(shares):.0%} of your full-throttle time below 220 km/h. "
                "That's power you asked for and didn't get.", [], 1.0)
    if n >= MIN_LAPS and not any(a["key"].startswith("lock") for a in out):
        shares = [x["abs_share"] for x in mine if x.get("abs_share") is not None]
        if abs_on and len(shares) >= MIN_LAPS and statistics.median(shares) >= 0.5:
            add("abs_busy", "You're leaning on the ABS",
                "Brake to just under where the ABS starts: it stops the car sooner.",
                f"ABS was working for {statistics.median(shares):.0%} of your braking.", [], 0.8)

    # Tyre pressures, hot: even across each axle, and at the car's ideal if we know it.
    psi_laps = [x["psi"] for x in mine if x.get("psi")]
    psi = None
    if len(psi_laps) >= MIN_LAPS:
        psi = [round(statistics.median(lap[i] for lap in psi_laps), 1) for i in range(4)]
        for axle, (a, b), target in (("front", (0, 1), target_psi[0] if target_psi else None),
                                     ("rear", (2, 3), target_psi[1] if target_psi else None)):
            if target:
                # Per wheel, against the ideal: this also evens out the axle.
                offs = [(i, psi[i] - target) for i in (a, b) if abs(psi[i] - target) >= TARGET_PSI]
                if offs:
                    do = " ".join(f"{WHEELS[i].capitalize()}: {'lower' if d > 0 else 'raise'} the cold pressure by "
                                  f"{abs(d):.1f} psi." for i, d in offs)
                    add(f"psi_{axle}", f"{axle.capitalize()} tyre pressures are off the car's ideal", do,
                        f"Hot they run {psi[a]:.1f} and {psi[b]:.1f} psi; this car's tyres work best at {target:.1f}.",
                        [], 0.9)
            elif abs(psi[a] - psi[b]) >= AXLE_PSI:
                hi, lo = (a, b) if psi[a] > psi[b] else (b, a)
                d = psi[hi] - psi[lo]
                add(f"psi_{axle}", f"{axle.capitalize()} tyre pressures are uneven when hot",
                    f"Start the {WHEELS[hi]} {d:.1f} psi lower than the {WHEELS[lo]}.",
                    f"Hot they run {psi[hi]:.1f} psi ({WHEELS[hi]}) against {psi[lo]:.1f}: the harder-worked side "
                    "heats up more. Evened out, both tyres on the axle grip the same.", [], 0.6)

    out.sort(key=lambda a: -a["weight"])
    return {"laps": n, "settings": now, "advice": out, "psi": psi, "target_psi": list(target_psi) if target_psi else None}


def ideal_pressures(install_dir: str | None, car: str) -> tuple[float, float] | None:
    """The car's ideal hot tyre pressures (front, rear) from its ``tyres.ini``,
    when the car's data folder is unpacked (many mods; not cars that ship only
    a packed data.acd). The default compound's (the first)."""
    import configparser
    from pathlib import Path

    if not install_dir or not car:
        return None
    path = Path(install_dir) / "content" / "cars" / car / "data" / "tyres.ini"
    try:
        if not path.is_file():
            return None
        cp = configparser.ConfigParser(strict=False, interpolation=None, inline_comment_prefixes=(";", "//"))
        cp.read(path, encoding="utf-8-sig")
        front = float(cp["FRONT"]["PRESSURE_IDEAL"])
        rear = float(cp["REAR"]["PRESSURE_IDEAL"])
    except (KeyError, ValueError, OSError, configparser.Error):
        return None
    return (front, rear) if 5 < front < 60 and 5 < rear < 60 else None
