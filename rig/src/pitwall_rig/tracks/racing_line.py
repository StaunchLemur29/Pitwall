"""An optimal racing line: the smoothest path the track's edges allow.

This is the classic *minimum-curvature* line, the usual first approximation of
the fastest line: out-in-out through single corners, straight-lining kinks and
chicanes where the width allows, compromised where corners link. It's purely
geometric (it doesn't know the car or where it brakes), so it's a guide for
where to place the car, not a lap-time prediction.

How: the line is the AI line moved sideways by an offset at every point, kept
``margin_m`` inside each edge. We minimise the sum of squared second
differences of the resulting points (≈ curvature² on an evenly spaced line), a
quadratic with box limits on each offset. Solved exactly with a primal
active-set method: hold the points that sit on an edge, solve the banded linear
system for the rest, update which points are held, repeat. Coarse to fine (a
Gauss-Seidel pass seeds the coarsest level) so few steps are needed. Pure Python.
"""

from __future__ import annotations

import math
from bisect import bisect_right

from .ac_files import TrackLine

# Coarse to fine: metres between points. Each level seeds the next.
LEVELS = (40.0, 20.0, 10.0, 5.0)
MAX_ACTIVE_SET_STEPS = 20000  # a safety stop; real tracks need far fewer
EPS = 1e-9


def _loop_length(line: TrackLine) -> float:
    # The gap from the last point back to the first counts too.
    return line.length + math.hypot(line.x[0] - line.x[-1], line.z[0] - line.z[-1])


def _interp_loop(ds_from: list[float], vals: list[float], loop: float, ds_to: list[float]) -> list[float]:
    """Linear interpolation of ``vals`` (sampled at ``ds_from``) round a closed loop."""
    n = len(ds_from)
    out = []
    for d in ds_to:
        j = max(0, min(bisect_right(ds_from, d) - 1, n - 1))
        k = (j + 1) % n
        d0 = ds_from[j]
        d1 = ds_from[k] if k else loop
        t = (d - d0) / (d1 - d0) if d1 > d0 else 0.0
        out.append(vals[j] + (vals[k] - vals[j]) * t)
    return out


def _normals(xs: list[float], zs: list[float]) -> list[tuple[float, float]]:
    """Unit vectors to the driver's left (same convention as TrackLine.normal)."""
    n = len(xs)
    out = []
    for i in range(n):
        a, b = (i - 1) % n, (i + 1) % n
        dx, dz = xs[b] - xs[a], zs[b] - zs[a]
        d = math.hypot(dx, dz) or 1.0
        out.append((dz / d, -dx / d))
    return out


class _Problem:
    """min ½αᵀHα + gᵀα with lo ≤ α ≤ hi, for points P = C + α·N on a closed loop.

    Objective ½Σ|P[k-1] - 2P[k] + P[k+1]|²: H[i][j] = w(i-j)·(N[i]·N[j]) with
    w = 6, -4, 1 for |i-j| = 0, 1, 2 (round the loop), and g[i] = N[i]·(second
    difference of the second differences of C at i).
    """

    def __init__(self, xs, zs, lo, hi) -> None:
        n = len(xs)
        self.n, self.xs, self.zs, self.lo, self.hi = n, xs, zs, lo, hi
        self._memo: dict[tuple, list[float]] = {}
        self.nrm = nrm = _normals(xs, zs)
        dot = lambda i, j: nrm[i][0] * nrm[j][0] + nrm[i][1] * nrm[j][1]
        self.h0 = [6.0 for _ in range(n)]
        self.h1 = [-4.0 * dot(i, (i + 1) % n) for i in range(n)]  # H[i][i+1]
        self.h2 = [1.0 * dot(i, (i + 2) % n) for i in range(n)]  # H[i][i+2]
        ex = [xs[(k - 1) % n] - 2 * xs[k] + xs[(k + 1) % n] for k in range(n)]
        ez = [zs[(k - 1) % n] - 2 * zs[k] + zs[(k + 1) % n] for k in range(n)]
        self.g = [
            nrm[i][0] * (ex[(i - 1) % n] - 2 * ex[i] + ex[(i + 1) % n])
            + nrm[i][1] * (ez[(i - 1) % n] - 2 * ez[i] + ez[(i + 1) % n])
            for i in range(n)
        ]

    def h(self, i: int, j: int) -> float:
        """H[i][j] (0 unless within 2 of each other round the loop)."""
        n = self.n
        d = (j - i) % n
        if d == 0:
            return self.h0[i]
        if d == 1:
            return self.h1[i]
        if d == 2:
            return self.h2[i]
        if d == n - 1:
            return self.h1[j]
        if d == n - 2:
            return self.h2[j]
        return 0.0

    def grad(self, alpha: list[float]) -> list[float]:
        n, h1, h2, a = self.n, self.h1, self.h2, alpha
        return [
            self.g[i]
            + self.h0[i] * a[i]
            + h1[i] * a[(i + 1) % n]
            + h1[i - 1] * a[i - 1]
            + h2[i] * a[(i + 2) % n]
            + h2[i - 2] * a[i - 2]
            for i in range(n)
        ]

    def value(self, alpha: list[float]) -> float:
        """½αᵀHα + gᵀα."""
        gr = self.grad(alpha)
        return 0.5 * sum(a * (gr[i] + self.g[i]) for i, a in enumerate(alpha))

    def solve_free(self, alpha: list[float], fixed: list[bool]) -> bool:
        """Set the free offsets to the exact minimiser with the fixed ones held.

        Nothing couples points more than 2 apart, so wherever two neighbouring
        points are held the problem splits: each stretch of free points between
        such pairs is a small banded (pentadiagonal) system of its own. Stretches
        whose held surroundings haven't changed are reused from last time.
        Returns False if no two neighbours are held (nowhere to split).
        """
        n = self.n
        start = next((i for i in range(n) if fixed[i] and fixed[(i + 1) % n]), None)
        if start is None:
            return False
        seg: list[int] = []
        last_free = -10
        for k in range(n - 2):
            i = (start + 2 + k) % n
            if fixed[i]:
                continue
            if seg and k - last_free > 2:
                self._segment(seg, alpha, fixed)
                seg = []
            seg.append(i)
            last_free = k
        if seg:
            self._segment(seg, alpha, fixed)
        return True

    def _segment(self, free: list[int], alpha: list[float], fixed: list[bool]) -> None:
        n = self.n
        # Held points inside or next to this stretch (all on an edge, so their
        # offsets are fixed by which edge): with the stretch, they decide the answer.
        held = []
        a, b = free[0], free[-1]
        span = (b - a) % n
        for k in range(-2, span + 3):
            j = (a + k) % n
            if fixed[j]:
                held.append((j, alpha[j]))
        key = (tuple(free), tuple(held))
        hit = self._memo.get(key)
        if hit is not None:
            for k, i in enumerate(free):
                alpha[i] = hit[k]
            return
        m = len(free)
        rhs = []
        for i in free:
            r = -self.g[i]
            for k in (-2, -1, 1, 2):
                j = (i + k) % n
                if fixed[j]:
                    r -= self.h(i, j) * alpha[j]
            rhs.append(r)
        # LDLᵀ of the symmetric pentadiagonal matrix (unit L with two sub-diagonals).
        d = [0.0] * m
        l1 = [0.0] * m  # L[k][k-1]
        l2 = [0.0] * m  # L[k][k-2]
        for k in range(m):
            a0 = self.h0[free[k]] + EPS
            if k >= 2:
                l2[k] = self.h(free[k], free[k - 2]) / d[k - 2]
            if k >= 1:
                a1 = self.h(free[k], free[k - 1])
                l1[k] = (a1 - (l2[k] * d[k - 2] * l1[k - 1] if k >= 2 else 0.0)) / d[k - 1]
            d[k] = a0 - l1[k] ** 2 * (d[k - 1] if k >= 1 else 0.0) - l2[k] ** 2 * (d[k - 2] if k >= 2 else 0.0)
        y = [0.0] * m
        for k in range(m):
            y[k] = rhs[k] - (l1[k] * y[k - 1] if k >= 1 else 0.0) - (l2[k] * y[k - 2] if k >= 2 else 0.0)
        x = [0.0] * m
        for k in range(m - 1, -1, -1):
            v = y[k] / d[k]
            if k + 1 < m:
                v -= l1[k + 1] * x[k + 1]
            if k + 2 < m:
                v -= l2[k + 2] * x[k + 2]
            x[k] = v
        if len(self._memo) > 20000:
            self._memo.clear()
        self._memo[key] = x
        for k, i in enumerate(free):
            alpha[i] = x[k]

    def gauss_seidel(self, alpha: list[float], sweeps: int) -> None:
        """Projected Gauss-Seidel: slow to finish but needs no starting edge contacts."""
        n, lo, hi, g, h0, h1, h2 = self.n, self.lo, self.hi, self.g, self.h0, self.h1, self.h2
        for _ in range(sweeps):
            biggest = 0.0
            for i in range(n):
                off = h1[i] * alpha[(i + 1) % n] + h1[i - 1] * alpha[i - 1] + h2[i] * alpha[(i + 2) % n] + h2[i - 2] * alpha[i - 2]
                a = alpha[i] + 1.6 * (-(g[i] + off) / h0[i] - alpha[i])
                a = lo[i] if a < lo[i] else min(a, hi[i])
                biggest = max(biggest, abs(a - alpha[i]))
                alpha[i] = a
            if biggest < 1e-6:
                break


def _solve(xs, zs, lo, hi, alpha: list[float]) -> None:
    """Primal active-set method for box limits (Nocedal & Wright, alg. 16.3).

    ``alpha`` must start inside the limits; it ends at the answer. Points on an
    edge are held there and the rest solved exactly; step towards that
    solution until something new touches an edge, and hold that too. Once
    nothing moves, let go of the edge point that most wants to move inwards.
    Done when none does.
    """
    prob = _Problem(xs, zs, lo, hi)
    n = len(xs)
    tol = 1e-9
    on = [0] * n  # -1 held on the lower limit, +1 on the upper, 0 free
    for i in range(n):
        if alpha[i] <= lo[i] + tol:
            on[i], alpha[i] = -1, lo[i]
        elif alpha[i] >= hi[i] - tol:
            on[i], alpha[i] = 1, hi[i]
    # A coarser solution touches the edges along whole runs of points; the
    # answer usually only at an apex. Start by holding just the middle pair of
    # each run: the first step re-holds any of the rest that still push out,
    # which is far cheaper than letting go of them one by one.
    if any(on) and not all(on):
        first = next(i for i in range(n) if on[i] == 0)
        k = 0
        while k < n:
            i = (first + k) % n
            if on[i] == 0:
                k += 1
                continue
            run = [i]
            while k + len(run) < n and on[(first + k + len(run)) % n] == on[i]:
                run.append((first + k + len(run)) % n)
            mid = len(run) // 2
            keep = set(run[max(0, mid - 1) : mid + 1])
            for j in run:
                if j not in keep:
                    on[j] = 0
            k += len(run)
    for _ in range(MAX_ACTIVE_SET_STEPS):
        target = alpha[:]
        if not prob.solve_free(target, [s != 0 for s in on]):
            prob.gauss_seidel(alpha, 2000)  # nothing to anchor the direct solve
            return
        step = [target[i] - alpha[i] for i in range(n)]
        if max(step) < 1e-7 and min(step) > -1e-7:
            # Let go of the one edge point that most wants to move inwards
            # (one at a time, or released neighbours can undo each other).
            mu = prob.grad(alpha)
            worst, pull = -1, 1e-7
            for i in range(n):
                v = -mu[i] if on[i] < 0 else mu[i] if on[i] > 0 else 0.0
                if v > pull:
                    worst, pull = i, v
            if worst < 0:
                return
            on[worst] = 0
            continue
        t = 1.0
        for i in range(n):
            v = step[i]
            if on[i] == 0 and v != 0:
                room = (lo[i] - alpha[i]) / v if v < 0 else (hi[i] - alpha[i]) / v
                t = min(t, max(0.0, room))
        for i in range(n):
            if on[i] == 0:
                alpha[i] += t * step[i]
                # Hold the points this step pushed onto an edge (not ones
                # sitting on it that are moving inwards).
                if step[i] < 0 and alpha[i] <= lo[i] + tol:
                    on[i], alpha[i] = -1, lo[i]
                elif step[i] > 0 and alpha[i] >= hi[i] - tol:
                    on[i], alpha[i] = 1, hi[i]


def optimal_offsets(line: TrackLine, margin_m: float = 1.2) -> list[float]:
    """Metres left of the AI line (negative = right) for the optimal line, one per
    line point. ``margin_m`` keeps the car's centre that far inside each edge
    (about half a car width plus a little; kerbs aren't assumed usable)."""
    n = len(line)
    if n < 20 or line.length <= 0:
        return [0.0] * n
    loop = _loop_length(line)
    prev_ds: list[float] | None = None
    prev_alpha: list[float] = []
    for step in LEVELS:
        count = int(round(loop / step))
        if count < 40 and step != LEVELS[-1]:
            continue  # short track: skip levels coarser than its corners
        count = max(count, 40)
        ds = [loop * k / count for k in range(count)]
        xs = _interp_loop(line.dist, line.x, loop, ds)
        zs = _interp_loop(line.dist, line.z, loop, ds)
        lo, hi = [], []
        for left, right in zip(
            _interp_loop(line.dist, line.side_left, loop, ds),
            _interp_loop(line.dist, line.side_right, loop, ds),
            strict=True,
        ):
            a, b = -(right - margin_m), left - margin_m
            if a > b:  # narrower than two margins: stay mid-track
                a = b = (left - right) / 2
            lo.append(a)
            hi.append(b)
        alpha = _interp_loop(prev_ds, prev_alpha, loop, ds) if prev_ds else [0.0] * count
        alpha = [min(max(a, lo[i]), hi[i]) for i, a in enumerate(alpha)]
        _solve(xs, zs, lo, hi, alpha)
        prev_ds, prev_alpha = ds, alpha
    assert prev_ds is not None
    out = _interp_loop(prev_ds, prev_alpha, loop, line.dist)
    # Back onto the AI line's own points, kept inside that point's edges.
    res = []
    for i, a in enumerate(out):
        left, right = line.side_left[i], line.side_right[i]
        if left + right > 2 * margin_m:
            res.append(min(max(a, -(right - margin_m)), left - margin_m))
        else:
            res.append((left - right) / 2)
    return res


def offsets_to_points(line: TrackLine, offsets: list[float]) -> list[tuple[float, float]]:
    pts = []
    for i, a in enumerate(offsets):
        nx, nz = line.normal(i)
        pts.append((line.x[i] + nx * a, line.z[i] + nz * a))
    return pts
