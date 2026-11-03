"""A track as Pitwall understands it: centre line, edges, named corners."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .ac_files import Section, TrackLine, lateral_position


@dataclass
class Corner:
    number: int  # 1-based, in lap order
    name: str  # from the track's own section names when available, else ""
    direction: str  # "L" | "R"
    grade: int  # rally-style severity: 1 = hairpin … 6 = flat-out kink
    entry: float  # lap progress 0..1
    apex: float
    exit: float
    apex_radius_m: float
    apex_index: int = 0

    @property
    def label(self) -> str:
        return self.name or f"Turn {self.number}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label
        return d


@dataclass
class TrackModel:
    track_key: str
    length_m: float
    line: TrackLine
    corners: list[Corner]
    sections: list[Section] = field(default_factory=list)
    source: str = "game"  # "game" (AC's files) or "laps" (learnt from driving)
    has_edges: bool = True

    def progress_of(self, i: int) -> float:
        return self.line.dist[i] / self.length_m if self.length_m else 0.0

    def index_at(self, progress: float) -> int:
        """Line index nearest to a lap progress value."""
        from bisect import bisect_left

        target = (progress % 1.0) * self.length_m
        i = bisect_left(self.line.dist, target)
        return min(i, len(self.line) - 1)

    def locate(self, x: float, z: float, hint: int | None = None) -> tuple[int, float, float]:
        return lateral_position(self.line, x, z, hint)

    def next_corner(self, progress: float) -> tuple[Corner, float] | None:
        """The corner you're in or approaching, and metres until its entry
        (0 while inside it)."""
        if not self.corners:
            return None
        for c in self.corners:
            if c.entry <= progress <= c.exit:
                return c, 0.0
        for c in self.corners:
            if c.entry > progress:
                return c, (c.entry - progress) * self.length_m
        c = self.corners[0]  # wrap to the next lap
        return c, (1 - progress + c.entry) * self.length_m

    def geometry(self, step_m: float = 3.0) -> dict[str, Any]:
        """Downsampled shape for the dashboard."""
        line = self.line
        idx = [0]
        for i in range(1, len(line)):
            if line.dist[i] - line.dist[idx[-1]] >= step_m:
                idx.append(i)
        left, right = line.edges() if self.has_edges else ([], [])
        r2 = lambda v: round(v, 1)  # noqa: E731
        return {
            "track_key": self.track_key,
            "length_m": round(self.length_m, 1),
            "source": self.source,
            "has_edges": self.has_edges,
            "progress": [round(self.progress_of(i), 5) for i in idx],
            "center": [[r2(line.x[i]), r2(line.z[i])] for i in idx],
            "left": [[r2(left[i][0]), r2(left[i][1])] for i in idx] if left else [],
            "right": [[r2(right[i][0]), r2(right[i][1])] for i in idx] if right else [],
            "corners": [c.to_dict() for c in self.corners],
            "sections": [asdict(s) for s in self.sections],
        }


# -- corner detection ------------------------------------------------------------


def _signed_curvature(line: TrackLine, window_m: float = 12.0) -> list[float]:
    """1/radius along the line; positive = right-hand turn (AC's world)."""
    n = len(line)
    spacing = line.length / max(1, n - 1)
    k = max(2, int(round(window_m / max(spacing, 0.1))))
    out = []
    for i in range(n):
        a, b = (i - k) % n, (i + k) % n
        h1 = (line.x[i] - line.x[a], line.z[i] - line.z[a])
        h2 = (line.x[b] - line.x[i], line.z[b] - line.z[i])
        turn = math.atan2(h1[0] * h2[1] - h1[1] * h2[0], h1[0] * h2[0] + h1[1] * h2[1])
        dist = math.hypot(*h1) + math.hypot(*h2)
        out.append(turn / (dist / 2) if dist > 0 else 0.0)
    return out


def _smooth(v: list[float], k: int) -> list[float]:
    n = len(v)
    if n == 0 or k <= 0:
        return v
    acc = sum(v[i % n] for i in range(-k, k + 1))
    out = []
    for i in range(n):
        out.append(acc / (2 * k + 1))
        acc += v[(i + k + 1) % n] - v[(i - k) % n]
    return out


def grade_for_radius(r: float) -> int:
    for g, limit in ((1, 25), (2, 45), (3, 75), (4, 120), (5, 200)):
        if r < limit:
            return g
    return 6


def detect_corners(
    line: TrackLine,
    sections: list[Section] | None = None,
    min_radius_m: float = 500.0,
    min_turn_deg: float = 15.0,
    merge_gap_m: float = 30.0,
) -> list[Corner]:
    """Find corners on a closed line: stretches tighter than ``min_radius_m``
    that turn at least ``min_turn_deg`` overall."""
    n = len(line)
    if n < 20 or line.length <= 0:
        return []
    spacing = line.length / (n - 1)
    curv = _smooth(_signed_curvature(line), max(1, int(15 / spacing)))
    thr = 1.0 / min_radius_m
    sign = lambda i: (1 if curv[i] > 0 else -1) if abs(curv[i]) > thr else 0  # noqa: E731

    # Start scanning on a straight so no corner straddles index 0.
    start = next((i for i in range(n) if sign(i) == 0), 0)
    runs: list[list[int]] = []  # [first, last, sign], indices relative to start
    for j in range(n):
        s = sign((start + j) % n)
        if s == 0:
            continue
        if runs and runs[-1][2] == s and (j - runs[-1][1]) * spacing <= merge_gap_m:
            runs[-1][1] = j
        else:
            runs.append([j, j, s])

    corners: list[Corner] = []
    for first, last, s in runs:
        idx = [(start + j) % n for j in range(first, last + 1)]
        total_turn = abs(sum(curv[i] for i in idx) * spacing)
        if math.degrees(total_turn) < min_turn_deg:
            continue
        apex = max(idx, key=lambda i: abs(curv[i]))
        radius = 1.0 / abs(curv[apex]) if curv[apex] else 1e9
        prog = lambda i: line.dist[i] / line.length  # noqa: E731
        corners.append(
            Corner(
                number=0,
                name="",
                direction="R" if s > 0 else "L",
                grade=grade_for_radius(radius),
                entry=prog(idx[0]),
                apex=prog(apex),
                exit=prog(idx[-1]),
                apex_radius_m=round(radius, 1),
                apex_index=apex,
            )
        )
    corners.sort(key=lambda c: c.entry)
    for i, c in enumerate(corners, 1):
        c.number = i
        if sections:
            c.name = _name_for(c, sections)
    # Several corners inside one named section (Les Combes is R-L-R): number them.
    by_name: dict[str, list[Corner]] = {}
    for c in corners:
        if c.name:
            by_name.setdefault(c.name, []).append(c)
    for group in by_name.values():
        if len(group) > 1:
            for k, c in enumerate(group, 1):
                c.name = f"{c.name} {k}"
    return corners


def _name_for(c: Corner, sections: list[Section]) -> str:
    # Prefer a section containing the apex; otherwise the nearest one that overlaps.
    for s in sections:
        if s.start <= c.apex <= s.end:
            return s.name
    for s in sections:
        if s.start <= c.exit and c.entry <= s.end:
            return s.name
    return ""
