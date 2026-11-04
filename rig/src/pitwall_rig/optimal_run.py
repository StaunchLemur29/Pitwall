"""The optimal run: the optimal racing line driven at this car's real grip.

1. **Learn the car** from your own fastest laps on this track: at each speed,
   the most lateral g, braking g and accelerating g it actually achieved
   (high percentiles, so one kerb strike doesn't count). Grip that grows with
   speed (aero) shows up as a v² term.
2. **Drive the optimal line** with a point-mass model (the usual first step in
   lap simulation): the fastest speed each bend allows, then braking and
   acceleration passes limited by a friction ellipse, so braking while turning
   gets less of each (trail braking falls out of this).
3. **Pedals**: brake = braking needed / most braking the car managed at that
   speed; throttle = acceleration needed / most it managed, with a little
   maintenance throttle when holding speed through a bend. They're estimates
   of what the pedals do, not readings.

The result is a trace in the same shape as a recorded lap (t, p, x, z, speed,
brake, gas, gear), so the analysis and the charts treat it like another lap.
It's only as good as the laps it learnt from: a car never pushed to its limit
looks slower than it is.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
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

    def lat(self, v: float) -> float:
        return self.lat0 + self.lat_k * v * v

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
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def _fit_v2(points: list[tuple[float, float, int]]) -> tuple[float, float]:
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


def _samples(tr: dict[str, list[float]]) -> list[tuple[float, float, float, float, float]]:
    """(v m/s, lateral m/s², longitudinal m/s², brake, gas) per sample, over
    a short window so position and speed noise averages out."""
    t, x, z, spd = tr.get("t", []), tr.get("x", []), tr.get("z", []), tr.get("speed", [])
    n = len(t)
    if n < 50 or len(x) != n:
        return []
    rate = (n - 1) / max(1e-6, t[-1] - t[0])
    k = max(1, int(round(rate * 0.15)))  # ±0.15 s
    out = []
    for i in range(k, n - k):
        if t[i] < 5 and tr["p"][i] > 0.9:
            continue  # still before the line
        a, b = i - k, i + k
        dt = t[b] - t[a]
        if dt <= 0:
            continue
        ax, az, bx, bz, cx, cz = x[a], z[a], x[i], z[i], x[b], z[b]
        l1 = math.hypot(bx - ax, bz - az)
        l2 = math.hypot(cx - bx, cz - bz)
        l3 = math.hypot(cx - ax, cz - az)
        if l1 < 0.5 or l2 < 0.5:
            continue  # nearly stopped
        area2 = abs((bx - ax) * (cz - az) - (bz - az) * (cx - ax))
        curv = 2 * area2 / (l1 * l2 * l3) if l3 > 0 else 0.0
        v = spd[i] / 3.6
        out.append((v, v * v * curv, (spd[b] - spd[a]) / 3.6 / dt, tr["brake"][i], tr["gas"][i]))
    return out


def learn_grip(traces: list[dict[str, list[float]]]) -> Grip | None:
    """The car's limits from laps on this track; None without enough driving."""
    samples = [s for tr in traces for s in _samples(tr)]
    if len(samples) < 500:
        return None
    bins: dict[int, dict[str, list[float]]] = {}
    for v, lat, lon, brake, gas in samples:
        b = bins.setdefault(int(v / BIN_MS), {"lat": [], "brake": [], "accel": []})
        b["lat"].append(lat)
        if brake > 0.3:
            b["brake"].append(-lon)
        if gas > 0.95 and brake < 0.05:
            b["accel"].append(lon)

    def table(key: str, q: float) -> list[tuple[float, float, int]]:
        return [
            ((k + 0.5) * BIN_MS, _percentile(b[key], q), len(b[key]))
            for k, b in sorted(bins.items())
            if len(b[key]) >= MIN_SAMPLES
        ]

    lat = table("lat", 0.97)
    brk = table("brake", 0.95)
    acc = table("accel", 0.9)
    if len(lat) < 3 or not brk or not acc:
        return None
    lat0, lat_k = _fit_v2(lat)
    brake0, brake_k = _fit_v2(brk)
    top = max(s[0] for s in samples)
    # Acceleration only falls with speed (power and drag): smooth out dips the
    # other way that are just a lack of samples.
    acc_v = [v for v, _, _ in acc]
    acc_a = [max(0.3, a) for _, a, _ in acc]
    for j in range(len(acc_a) - 2, -1, -1):
        acc_a[j] = max(acc_a[j], acc_a[j + 1])
    return Grip(
        lat0=max(3.0, lat0), lat_k=lat_k,
        brake0=max(3.0, brake0), brake_k=brake_k,
        accel_v=acc_v, accel_a=acc_a, top_speed=top,
    )


# -- driving the optimal line ------------------------------------------------------------


def _curvature(xs: list[float], zs: list[float], ds: list[float], window_m: float = 8.0) -> list[float]:
    """|1/radius| along a closed path, over ±window_m."""
    n = len(xs)
    spacing = sum(ds) / n
    k = max(1, int(round(window_m / max(spacing, 0.1))))
    out = []
    for i in range(n):
        a, b = (i - k) % n, (i + k) % n
        h1 = (xs[i] - xs[a], zs[i] - zs[a])
        h2 = (xs[b] - xs[i], zs[b] - zs[i])
        turn = math.atan2(h1[0] * h2[1] - h1[1] * h2[0], h1[0] * h2[0] + h1[1] * h2[1])
        d = math.hypot(*h1) + math.hypot(*h2)
        out.append(abs(turn) / (d / 2) if d > 0 else 0.0)
    return out


def _left(grip_long: float, v: float, curv: float, lat_max: float) -> float:
    """Longitudinal grip left over while turning (friction ellipse)."""
    use = v * v * curv / lat_max if lat_max > 0 else 1.0
    return grip_long * math.sqrt(max(0.0, 1.0 - use * use))


def simulate(model: TrackModel, grip: Grip) -> dict[str, list[float]] | None:
    """The optimal run as a lap trace; None if the track has no optimal line."""
    off = model.optimal(compute=False)
    if not off:
        return None
    line = model.line
    pts = offsets_to_points(line, off)
    n = len(pts)
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    ds = [math.hypot(xs[(i + 1) % n] - xs[i], zs[(i + 1) % n] - zs[i]) for i in range(n)]  # i → i+1
    curv = _curvature(xs, zs, ds)
    vmax = []
    for c in curv:
        # Fastest the bend allows: v²·c = lat0 + lat_k·v².
        v = math.sqrt(grip.lat0 / (c - grip.lat_k)) if c > grip.lat_k else grip.top_speed
        vmax.append(min(v, grip.top_speed))
    start = min(range(n), key=vmax.__getitem__)  # the slowest point: both passes start there
    v = vmax[:]
    for _ in range(2):  # twice round, so the start line wraps properly
        for k in range(1, n + 1):  # accelerating forwards
            i, j = (start + k - 1) % n, (start + k) % n
            a = _left(grip.accel(v[i]), v[i], curv[i], grip.lat(v[i]))
            v[j] = min(v[j], math.sqrt(v[i] ** 2 + 2 * a * ds[i]))
        for k in range(1, n + 1):  # braking, worked out backwards
            j, i = (start - k + 1) % n, (start - k) % n
            a = _left(grip.brake(v[j]), v[j], curv[j], grip.lat(v[j]))
            v[i] = min(v[i], math.sqrt(v[j] ** 2 + 2 * a * ds[i]))

    tr: dict[str, list[float]] = {k: [] for k in ("t", "p", "x", "z", "speed", "brake", "gas", "gear")}
    t = 0.0
    length = model.length_m or line.length
    for i in range(n):
        if i:
            t += ds[i - 1] / max(0.5, (v[i - 1] + v[i]) / 2)
        nxt = (i + 1) % n
        acc = (v[nxt] ** 2 - v[i] ** 2) / (2 * ds[i]) if ds[i] > 0 else 0.0
        if acc < -0.5:
            brake, gas = min(1.0, -acc / grip.brake(v[i])), 0.0
        else:
            room = grip.accel(v[i])
            brake = 0.0
            gas = 1.0 if v[i] >= grip.top_speed * 0.995 else max(0.2, min(1.0, acc / room)) if room > 0 else 1.0
        tr["t"].append(round(t, 3))
        tr["p"].append(round(line.dist[i] / length, 5))
        tr["x"].append(round(xs[i], 2))
        tr["z"].append(round(zs[i], 2))
        tr["speed"].append(round(v[i] * 3.6, 1))
        tr["brake"].append(round(brake, 3))
        tr["gas"].append(round(gas, 3))
        tr["gear"].append(0)  # unknown
    return tr


def lap_time(tr: dict[str, list[float]]) -> float:
    """Seconds round the whole loop (the last point back to the first)."""
    if not tr["t"]:
        return 0.0
    gap = math.hypot(tr["x"][0] - tr["x"][-1], tr["z"][0] - tr["z"][-1])
    return tr["t"][-1] + gap / max(0.5, (tr["speed"][0] + tr["speed"][-1]) / 2 / 3.6)
