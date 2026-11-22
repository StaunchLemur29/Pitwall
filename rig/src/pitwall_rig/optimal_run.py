"""The optimal run: the optimal racing line driven at this car's real grip.

1. **Learn the car** from your own fastest laps on this track: at each speed,
   the most lateral g, braking g and accelerating g it actually achieved
   (high percentiles, so one kerb strike doesn't count). Grip that grows with
   speed (aero) shows up as a v² term. The fit follows the top of what the car
   did: speeds where you never cornered hard say nothing about its limit.
2. **Hills.** A compression presses the car into the road and a crest
   unloads it (Eau Rouge: over twice the load at the bottom, under half over
   the top), and a slope adds to or takes from braking and acceleration. Both
   are taken out of what's learnt (so it's the car on flat ground) and put
   back in along the line being driven, from the track's own elevation.
3. **Drive the optimal line** with a point-mass model (the usual first step in
   lap simulation): the fastest speed each bend allows, then braking and
   acceleration passes limited by a friction ellipse, so braking while turning
   gets less of each (trail braking falls out of this). Acceleration is the
   lesser of what the engine gives at that speed and what the tyres have left.
4. **Pedals**: brake = braking needed / most braking the car managed at that
   speed; throttle = acceleration needed / most it managed, with a little
   maintenance throttle when holding speed through a bend. They're estimates
   of what the pedals do, not readings.

The result is a trace in the same shape as a recorded lap (t, p, x, z, speed,
brake, gas, gear), so the analysis and the charts treat it like another lap.
It's only as good as the laps it learnt from: a car never pushed to its limit
looks slower than it is. Not modelled: banking and camber, kerbs, tyre wear
and temperature, wind, the car's balance (it's a point).
"""

from __future__ import annotations

import itertools
import math
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .tracks.model import TrackModel
from .tracks.racing_line import offsets_to_points

G = 9.81
BIN_MS = 10 / 3.6  # speed bins of 10 km/h
MIN_SAMPLES = 25  # per bin, before a bin counts


@dataclass
class Grip:
    """What the car managed, as functions of speed (m/s → m/s²)."""

    lat0: float  # lateral: lat0 + lat_k·v²
    lat_k: float
    brake0: float  # braking: brake0 + brake_k·v²
    brake_k: float
    accel_v: list[float]  # accelerating: table by speed
    accel_a: list[float]
    top_speed: float  # m/s, the fastest it's been
    gears: dict[int, int] = field(default_factory=dict)  # speed bin → the gear you pull in at that speed
    traction0: float = 0.0  # most the driven tyres put down at low speed (0: not known, use the engine table alone)
    local: list[float] = field(default_factory=list)  # per stretch of the lap: extra grip there (banking, camber)

    def here(self, progress: float) -> float:
        """How much more grip this place has than the car's usual (1.0 = none)."""
        if not self.local:
            return 1.0
        return self.local[min(len(self.local) - 1, int((progress % 1.0) * len(self.local)))]

    def traction(self, v: float) -> float:
        """Most the tyres can accelerate the car at this speed (grows with aero like the rest)."""
        if self.traction0 <= 0:
            return float("inf")
        return self.traction0 * self.lat(v) / self.lat0

    def gear(self, v: float) -> int:
        """The gear you use on the power at this speed (0: not known)."""
        if not self.gears:
            return 0
        b = int(v / BIN_MS)
        if b in self.gears:
            return self.gears[b]
        near = min(self.gears, key=lambda k: abs(k - b))
        return self.gears[near]

    def lat(self, v: float) -> float:
        return self.lat0 + self.lat_k * v * v

    def lat_on(self, v: float, load: float) -> float:
        """Lateral grip with the hills in: only the weight's share changes with the load, not the aero's."""
        return self.lat0 * load + self.lat_k * v * v

    def brake(self, v: float) -> float:
        return self.brake0 + self.brake_k * v * v

    def accel(self, v: float) -> float:
        if v >= self.top_speed:
            return 0.0
        vs, a = self.accel_v, self.accel_a
        if v <= vs[0]:
            return a[0]
        if v >= vs[-1]:
            # Fade to nothing at the top speed you've reached.
            span = max(0.5, self.top_speed - vs[-1])
            return a[-1] * max(0.0, (self.top_speed - v) / span)
        j = bisect_left(vs, v)
        k = (v - vs[j - 1]) / (vs[j] - vs[j - 1])
        return a[j - 1] + (a[j] - a[j - 1]) * k

    def to_dict(self) -> dict[str, Any]:
        """Summary in g for the UI and logs."""
        return {
            "lat_g_100": round(self.lat(100 / 3.6) / G, 2),
            "lat_g_200": round(self.lat(200 / 3.6) / G, 2),
            "brake_g_100": round(self.brake(100 / 3.6) / G, 2),
            "brake_g_200": round(self.brake(200 / 3.6) / G, 2),
            "top_kmh": round(self.top_speed * 3.6),
        }


# -- learning the car -------------------------------------------------------------


def _percentile(v: list[float], q: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def _fit_v2(points: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Weighted least squares y = a + k·v² over (v, y, weight); k kept ≥ 0."""
    sw = sum(w for _, _, w in points)
    if sw == 0:
        return 0.0, 0.0
    mx = sum(w * v * v for v, _, w in points) / sw
    my = sum(w * y for _, y, w in points) / sw
    sxx = sum(w * (v * v - mx) ** 2 for v, _, w in points)
    sxy = sum(w * (v * v - mx) * (y - my) for v, y, w in points)
    k = sxy / sxx if sxx > 1e-9 else 0.0
    if k < 0:
        return my, 0.0
    return my - k * mx, k


LOAD_MIN, LOAD_MAX = 0.25, 2.5  # limits on the hill factor (below ~0.25 the car's nearly flying)
HILL_WINDOW_M = 40.0  # a car's springs and its own flight smooth out anything shorter


def hills(ys: list[float], ds: list[float], closed: bool, window_m: float = HILL_WINDOW_M
          ) -> tuple[list[float], list[float]]:
    """Along a path (heights, and metres from each point to the next): the
    vertical curvature (1/m: positive in a dip, negative over a crest) and the
    slope (sine of the angle: positive uphill), each over ±window_m."""
    n = len(ys)
    if n < 5 or not any(ys):
        return [0.0] * n, [0.0] * n
    spacing = max(0.1, sum(ds[: n - 1]) / (n - 1))
    k = max(1, round(window_m / spacing))
    kv, slope = [], []
    for i in range(n):
        a, b = i - k, i + k
        if closed:
            a, b = a % n, b % n
        elif a < 0 or b >= n:
            kv.append(0.0)
            slope.append(0.0)
            continue
        h = k * spacing
        kv.append((ys[a] - 2 * ys[i] + ys[b]) / (h * h))
        slope.append(max(-0.5, min(0.5, (ys[b] - ys[a]) / (2 * h))))
    return kv, slope


def load_factor(v: float, kv: float) -> float:
    """How hard the car is pressed into the road, as a multiple of its weight."""
    return max(LOAD_MIN, min(LOAD_MAX, 1.0 + v * v * kv / G))


def _samples(tr: dict[str, list[float]]) -> list[tuple[float, float, float, float, float, float, float]]:
    """(v m/s, lateral m/s², longitudinal m/s², brake, gas, load, lap progress) per sample, over
    a short window so position and speed noise averages out. Longitudinal is
    what the tyres did (the slope's share removed); ``load`` is how hard the
    hills pressed the car into the road there."""
    t, x, z, spd = tr.get("t", []), tr.get("x", []), tr.get("z", []), tr.get("speed", [])
    n = len(t)
    if n < 50 or len(x) != n:
        return []
    # Samples a second, from the usual gap between them (not first to last: a
    # pause, a rewind or a stray sample at either end would throw that off).
    gaps = sorted(b - a for a, b in itertools.pairwise(t) if b > a)
    if not gaps:
        return []
    rate = 1.0 / gaps[len(gaps) // 2]
    k = max(1, round(rate * 0.15))  # ±0.15 s
    y = tr.get("y") or []
    kv, slope = _trace_hills(x, y, z) if len(y) == n else ([0.0] * n, [0.0] * n)
    out = []
    for i in range(k, n - k):
        if t[i] < 5 and tr["p"][i] > 0.9:
            continue  # still before the line
        a, b = i - k, i + k
        dt = t[b] - t[a]
        if dt <= 0 or dt > 4 * k / rate:
            continue  # the clock jumped inside the window (a pause, a rewind)
        ax, az, bx, bz, cx, cz = x[a], z[a], x[i], z[i], x[b], z[b]
        l1 = math.hypot(bx - ax, bz - az)
        l2 = math.hypot(cx - bx, cz - bz)
        l3 = math.hypot(cx - ax, cz - az)
        if l1 < 0.5 or l2 < 0.5:
            continue  # nearly stopped
        area2 = abs((bx - ax) * (cz - az) - (bz - az) * (cx - ax))
        curv = 2 * area2 / (l1 * l2 * l3) if l3 > 0 else 0.0
        v = spd[i] / 3.6
        load = load_factor(v, kv[i])
        lon = (spd[b] - spd[a]) / 3.6 / dt + G * slope[i]
        out.append((v, v * v * curv, lon, tr["brake"][i], tr["gas"][i], load, tr["p"][i]))
    return out


def _trace_hills(x: list[float], y: list[float], z: list[float]) -> tuple[list[float], list[float]]:
    """Vertical curvature and slope at each sample of a lap, from a copy of its
    path resampled every 2 m (samples bunch up at low speed)."""
    n = len(x)
    dist = [0.0]
    for i in range(1, n):
        dist.append(dist[-1] + math.hypot(x[i] - x[i - 1], z[i] - z[i - 1]))
    step = 2.0
    m = int(dist[-1] / step)
    if m < 30:
        return [0.0] * n, [0.0] * n
    ys, j = [], 0
    for q in range(m + 1):
        d = q * step
        while j < n - 2 and dist[j + 1] < d:
            j += 1
        span = dist[j + 1] - dist[j]
        ys.append(y[j] + (y[j + 1] - y[j]) * ((d - dist[j]) / span if span > 0 else 0.0))
    kv, slope = hills(ys, [step] * len(ys), closed=False)
    at = [min(m, round(d / step)) for d in dist]
    return [kv[q] for q in at], [slope[q] for q in at]


def lap_gears(tr: dict[str, list[float]]) -> dict[int, Counter[int]]:
    """One lap's gears on the power per speed bin (for learn_gears; kept per lap)."""
    seen: dict[int, Counter[int]] = {}
    for v, gas, gear in zip(tr.get("speed", []), tr.get("gas", []), tr.get("gear", []), strict=False):
        if gas > 0.2 and gear >= 1 and v > 20:
            seen.setdefault(int(v / 3.6 / BIN_MS), Counter())[int(gear)] += 1
    return seen


def learn_gears(traces: list[dict[str, list[float]]],
                per_lap: list[dict[int, Counter[int]]] | None = None) -> dict[int, int]:
    """Which gear you're in on the power at each speed (10 km/h bins): the
    commonest, and never a lower gear at a higher speed."""
    seen: dict[int, Counter[int]] = {}
    for lap in per_lap if per_lap is not None else [lap_gears(tr) for tr in traces]:
        for b, c in lap.items():
            seen.setdefault(b, Counter()).update(c)
    out: dict[int, int] = {}
    top = 0
    for b in sorted(seen):
        if sum(seen[b].values()) >= 10:
            top = max(top, seen[b].most_common(1)[0][0])
            out[b] = top
    return out


def _fit_top(points: list[tuple[float, float, int]], below: float = 0.12, band: float = 0.12) -> tuple[float, float]:
    """y = a + k·v² along the top of the points (v, y, samples). A point below
    the curve counts for little: a speed where the car was never asked for all
    it had says nothing about its limit. A point within ``band`` above counts
    in full; further above it counts for less the further it is (a kerb, a
    banked corner, a glitch). k kept ≥ 0."""
    pts = [(v, y, math.sqrt(w)) for v, y, w in points]
    a, k = _fit_v2(pts)
    for _ in range(40):
        again = []
        for v, y, w in pts:
            fit = a + k * v * v
            if y < fit:
                w *= below
            elif fit > 0 and y > fit * (1 + band):
                w *= fit * band / (y - fit)
            again.append((v, y, w))
        a, k = _fit_v2(again)
    return a, k


def lap_samples(tr: dict[str, list[float]]) -> list[tuple[float, float, float, float, float, float, float]]:
    """One lap's samples for learn_grip (the slow part): worked out once per
    lap and kept by the caller, so redoing the optimal run is quick."""
    return _samples(tr)


def learn_grip(traces: list[dict[str, list[float]]],
               per_lap: list[list[tuple[float, ...]]] | None = None,
               gears: list[dict[int, Counter[int]]] | None = None) -> Grip | None:
    """The car's limits from laps on this track; None without enough driving.
    ``per_lap`` / ``gears``: each lap's ``lap_samples`` / ``lap_gears``, if
    already worked out (the slow part: kept per lap by the caller)."""
    if per_lap is None:
        per_lap = [_samples(tr) for tr in traces]
    samples = [s for lap in per_lap for s in lap]
    if len(samples) < 500:
        return None
    # Sorted into speed bins once (the fits below go over them several times).
    by_bin: dict[str, dict[int, list[tuple[float, float, float]]]] = {"lat": {}, "brake": {}, "accel": {}}
    for v, lat, lon, brake, gas, load, _p in samples:
        k = int(v / BIN_MS)
        by_bin["lat"].setdefault(k, []).append((v, lat, load))
        if brake > 0.3:
            by_bin["brake"].setdefault(k, []).append((v, -lon, load))
        if gas > 0.95 and brake < 0.05:
            by_bin["accel"].setdefault(k, []).append((v, lon, 1.0))

    def table(key: str, q: float, lat_k: float = 0.0, brake_k: float = 0.0) -> list[tuple[float, float, int]]:
        # On flat ground: only the weight's share of the grip changes with the
        # load (a + k·v²: a is the weight's, k·v² the aero's).
        aero = lat_k if key == "lat" else brake_k if key == "brake" else None
        out = []
        for k, rows in sorted(by_bin[key].items()):
            if len(rows) < MIN_SAMPLES:
                continue
            if aero is None:
                vals = [val for _v, val, _l in rows]
            else:
                vals = [(val - aero * v * v) / load + aero * v * v for v, val, load in rows]
            out.append(((k + 0.5) * BIN_MS, _percentile(vals, q), len(vals)))
        return out

    acc = table("accel", 0.9)
    lat_k = brake_k = 0.0
    for _ in range(3):  # the aero share isn't known until it's fitted: settle on it
        lat = table("lat", 0.97, lat_k=lat_k)
        brk = table("brake", 0.95, brake_k=brake_k)
        if len(lat) < 3 or not brk or not acc:
            return None
        lat0, lat_k = _fit_top(lat)
        brake0, brake_k = _fit_top(brk)
    top = max(s[0] for s in samples)
    # Acceleration only falls with speed (power and drag): smooth out dips the
    # other way that are just a lack of samples.
    acc_v = [v for v, _, _ in acc]
    acc_a = [max(0.3, a) for _, a, _ in acc]
    for j in range(len(acc_a) - 2, -1, -1):
        acc_a[j] = max(acc_a[j], acc_a[j + 1])
    lat0 = max(3.0, lat0)
    grip = _grip(lat0, lat_k, brake0, brake_k, acc_v, acc_a, top, traces, gears)
    grip.local = _local_grip(per_lap, grip)
    return grip


LOCAL_BINS = 1000  # along the lap
LOCAL_MAX = 1.6  # the most a place can add (a steeply banked corner)
LOCAL_FROM = 1.05  # less than this over the car's usual grip isn't worth a correction


def _local_grip(per_lap: list[list[tuple[float, ...]]], grip: Grip) -> list[float]:
    """Places where the car cornered harder than its grip elsewhere allows:
    banking, camber, a kerb you can lean on. Per stretch of the lap, how much
    more (1.0 = no more). From what it did there, steadily (the middle of a few
    stretches, so one spike doesn't count) and, with three laps or more, on more
    than one of them. It only ever adds: the optimal run is never told a place
    has less grip than you've used there."""
    laps: list[list[float]] = []
    for lap in per_lap:
        cells: list[list[float]] = [[] for _ in range(LOCAL_BINS)]
        for v, lat, _lon, _brake, _gas, load, p in lap:
            if v > 12:
                cells[min(LOCAL_BINS - 1, int(p * LOCAL_BINS))].append(lat / grip.lat_on(v, load))
        mid = [sorted(c)[len(c) // 2] if c else 0.0 for c in cells]
        smooth = []
        for i in range(LOCAL_BINS):  # the middle of five stretches
            w = sorted(mid[(i + d) % LOCAL_BINS] for d in (-2, -1, 0, 1, 2))
            smooth.append(w[2])
        if any(smooth):
            laps.append(smooth)
    if not laps:
        return []
    out = []
    for i in range(LOCAL_BINS):
        vals = sorted(lap[i] for lap in laps)
        r = vals[-2] if len(vals) >= 3 else vals[0]  # seen on more than one lap
        out.append(round(min(LOCAL_MAX, r), 3) if r >= LOCAL_FROM else 1.0)
    return out if any(x > 1.0 for x in out) else []


def _grip(lat0: float, lat_k: float, brake0: float, brake_k: float, acc_v: list[float], acc_a: list[float],
          top: float, traces: list[dict[str, list[float]]],
          gears: list[dict[int, Counter[int]]] | None = None) -> Grip:
    return Grip(
        lat0=lat0, lat_k=lat_k,
        brake0=max(3.0, brake0), brake_k=brake_k,
        accel_v=acc_v, accel_a=acc_a, top_speed=top, gears=learn_gears(traces, gears),
        # The tyres had at least this to give at the slowest speed you were flat out at.
        traction0=acc_a[0] * lat0 / (lat0 + lat_k * acc_v[0] ** 2),
    )


# -- driving the optimal line ------------------------------------------------------------


def _curvature(xs: list[float], zs: list[float], ds: list[float], window_m: float = 8.0) -> list[float]:
    """|1/radius| along a closed path, over ±window_m."""
    n = len(xs)
    spacing = sum(ds) / n
    k = max(1, round(window_m / max(spacing, 0.1)))
    out = []
    for i in range(n):
        a, b = (i - k) % n, (i + k) % n
        h1 = (xs[i] - xs[a], zs[i] - zs[a])
        h2 = (xs[b] - xs[i], zs[b] - zs[i])
        turn = math.atan2(h1[0] * h2[1] - h1[1] * h2[0], h1[0] * h2[0] + h1[1] * h2[1])
        d = math.hypot(*h1) + math.hypot(*h2)
        out.append(abs(turn) / (d / 2) if d > 0 else 0.0)
    return out


def _corner_speed(grip: Grip, curv: float, kv: float, here: float = 1.0) -> float:
    """Fastest the bend allows: where v²·curv reaches the grip there is at that
    speed and that load. Over a crest the load falls as you go faster, so
    there's a limit even on a gentle bend."""
    top = grip.top_speed
    if curv <= 1e-6:
        return top

    def spare(v: float) -> float:
        return grip.lat_on(v, load_factor(v, kv)) * here - v * v * curv

    if spare(top) >= 0:
        return top
    lo, hi = 0.0, top
    step = top / 24
    v = step
    while v < top and spare(v) >= 0:  # the first speed that's too fast
        lo, v = v, v + step
    hi = min(v, top)
    for _ in range(18):
        mid = (lo + hi) / 2
        if spare(mid) >= 0:
            lo = mid
        else:
            hi = mid
    return lo


def simulate(model: TrackModel, grip: Grip) -> dict[str, list[float]] | None:
    """The optimal run as a lap trace; None if the track has no optimal line."""
    off = model.optimal(compute=False)
    if not off:
        return None
    line = model.line
    pts = offsets_to_points(line, off)
    length = model.length_m or line.length
    return simulate_path([p[0] for p in pts], [p[1] for p in pts], [d / length for d in line.dist], grip,
                         ys=list(line.y) if len(line.y) == len(pts) else None)


def simulate_path(xs: list[float], zs: list[float], progress: list[float], grip: Grip,
                  ys: list[float] | None = None) -> dict[str, list[float]]:
    """Any closed path driven at the car's grip, as a lap trace. ``progress``:
    lap progress (0..1) of each point. ``ys``: its heights, for the hills."""
    n = len(xs)
    ds = [math.hypot(xs[(i + 1) % n] - xs[i], zs[(i + 1) % n] - zs[i]) for i in range(n)]  # i → i+1
    curv = _curvature(xs, zs, ds)
    kv, slope = hills(ys, ds, closed=True) if ys else ([0.0] * n, [0.0] * n)
    here = [grip.here(p) for p in progress]
    vmax = [_corner_speed(grip, curv[i], kv[i], here[i]) for i in range(n)]

    def left(i: int, v: float, long_grip: float) -> float:
        """Longitudinal grip left over while turning (friction ellipse), at this point's load."""
        load = load_factor(v, kv[i])
        lat_max = grip.lat_on(v, load) * here[i]
        use = v * v * curv[i] / lat_max if lat_max > 0 else 1.0
        return long_grip * (lat_max / grip.lat(v)) * math.sqrt(max(0.0, 1.0 - use * use))

    def drive(i: int, v: float) -> float:
        """Most the car can accelerate here: the engine or the tyres, whichever gives less; less the climb."""
        return min(grip.accel(v), left(i, v, grip.traction(v))) - G * slope[i]

    def slow(i: int, v: float) -> float:
        """Most it can brake here (a climb helps)."""
        return left(i, v, grip.brake(v)) + G * slope[i]

    start = min(range(n), key=vmax.__getitem__)  # the slowest point: both passes start there
    v = vmax[:]
    for _ in range(2):  # twice round, so the start line wraps properly
        for k in range(1, n + 1):  # accelerating forwards
            i, j = (start + k - 1) % n, (start + k) % n
            v[j] = min(v[j], math.sqrt(max(0.0, v[i] ** 2 + 2 * drive(i, v[i]) * ds[i])))
        for k in range(1, n + 1):  # braking, worked out backwards
            j, i = (start - k + 1) % n, (start - k) % n
            v[i] = min(v[i], math.sqrt(max(0.0, v[j] ** 2 + 2 * slow(j, v[j]) * ds[i])))

    tr: dict[str, list[float]] = {k: [] for k in ("t", "p", "x", "z", "speed", "brake", "gas", "gear")}
    t = 0.0
    for i in range(n):
        if i:
            t += ds[i - 1] / max(0.5, (v[i - 1] + v[i]) / 2)
        nxt = (i + 1) % n
        acc = (v[nxt] ** 2 - v[i] ** 2) / (2 * ds[i]) if ds[i] > 0 else 0.0
        tyres = acc + G * slope[i]  # what the tyres are doing: the slope does the rest
        if tyres < -0.5:
            brake, gas = min(1.0, -tyres / max(0.1, grip.brake(v[i]) * grip.lat_on(v[i], load_factor(v[i], kv[i])) * here[i] / grip.lat(v[i]))), 0.0
        else:
            room = grip.accel(v[i])
            brake = 0.0
            gas = 1.0 if v[i] >= grip.top_speed * 0.995 else max(0.2, min(1.0, tyres / room)) if room > 0 else 1.0
        tr["t"].append(round(t, 3))
        tr["p"].append(round(progress[i], 5))
        tr["x"].append(round(xs[i], 2))
        tr["z"].append(round(zs[i], 2))
        tr["speed"].append(round(v[i] * 3.6, 1))
        tr["brake"].append(round(brake, 3))
        tr["gas"].append(round(gas, 3))
        tr["gear"].append(grip.gear(v[i]))  # the gear you pull in at this speed (0: unknown)
    return tr


def lap_time(tr: dict[str, list[float]]) -> float:
    """Seconds round the whole loop (the last point back to the first)."""
    if not tr["t"]:
        return 0.0
    gap = math.hypot(tr["x"][0] - tr["x"][-1], tr["z"][0] - tr["z"][-1])
    return tr["t"][-1] + gap / max(0.5, (tr["speed"][0] + tr["speed"][-1]) / 2 / 3.6)
