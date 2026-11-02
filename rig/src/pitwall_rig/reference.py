"""Live delta against a reference lap, by position on track."""

from __future__ import annotations

from bisect import bisect_left


class ReferenceLap:
    """Time-at-progress lookup built from a lap trace (``p`` and ``t`` channels)."""

    def __init__(self, trace: dict[str, list[float]], lap_time_ms: int, lap_id: int | None = None):
        self.lap_id = lap_id
        self.lap_time_ms = lap_time_ms
        ps, ts = trace.get("p", []), trace.get("t", [])
        # The spline zero and the timing line don't always coincide, so the first
        # few samples can read ~0.99. Keep a strictly increasing progress series.
        self._p: list[float] = []
        self._t: list[float] = []
        for p, t in zip(ps, ts, strict=False):
            if t < 5 and p > 0.9:
                continue
            if not self._p or p > self._p[-1]:
                self._p.append(p)
                self._t.append(t)

    def __bool__(self) -> bool:
        return len(self._p) > 10

    def time_at(self, progress: float) -> float | None:
        if not self:
            return None
        if progress <= self._p[0]:
            return self._t[0]
        if progress >= self._p[-1]:
            return self._t[-1]
        i = bisect_left(self._p, progress)
        p0, p1, t0, t1 = self._p[i - 1], self._p[i], self._t[i - 1], self._t[i]
        return t0 + (t1 - t0) * (progress - p0) / (p1 - p0)

    def delta(self, progress: float, lap_time_ms: int) -> float | None:
        """Seconds behind (+) or ahead (−) of the reference at this point."""
        if lap_time_ms < 3000 and progress > 0.9:
            return None  # just crossed the line, progress hasn't wrapped yet
        ref = self.time_at(progress)
        if ref is None:
            return None
        return round(lap_time_ms / 1000.0 - ref, 3)


def downsample(trace: dict[str, list[float]], hz: float) -> dict[str, list[float]]:
    """Keep roughly ``hz`` samples per second of lap time."""
    ts = trace.get("t", [])
    if not ts or hz <= 0:
        return trace
    step = 1.0 / hz
    keep: list[int] = []
    next_t = -1e9
    for i, t in enumerate(ts):
        if t >= next_t:
            keep.append(i)
            next_t = t + step
    if keep[-1] != len(ts) - 1:
        keep.append(len(ts) - 1)
    return {k: [v[i] for i in keep] for k, v in trace.items()}
