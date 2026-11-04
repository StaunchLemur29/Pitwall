"""A track as Pitwall understands it: centre line, edges, named corners."""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from .ac_files import Section, TrackLine, lateral_position
from .racing_line import offsets_to_points, optimal_offsets

# Optimal lines already worked out, by track (models get rebuilt; the line doesn't change).
_OPTIMAL: dict[tuple[str, int, float], list[float]] = {}
_OPTIMAL_LOCK = threading.Lock()  # one solve at a time; a second asker waits for it


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
    chapters: list[Any] = field(default_factory=list)  # from a track pack
    practice: list[Any] = field(default_factory=list)  # PracticeSection, filled in __post_init__

    def __post_init__(self) -> None:
        if not self.practice:
            self.practice = practice_sections(self.corners, self.length_m)

    def _optimal_key(self) -> tuple[str, int, float]:
        return (self.track_key, len(self.line), round(self.line.length, 1))

    def optimal_ready(self) -> bool:
        """True once the optimal line is known (or there can't be one)."""
        return not self.has_edges or self._optimal_key() in _OPTIMAL

    def optimal(self, compute: bool = True) -> list[float] | None:
        """The optimal racing line as metres left of the AI line, per line point.
        None without track edges, or if not worked out yet and ``compute`` is False."""
        if not self.has_edges:
            return None
        key = self._optimal_key()
        if key in _OPTIMAL:
            return _OPTIMAL[key]
        if not compute:
            return None
        with _OPTIMAL_LOCK:
            if key not in _OPTIMAL:
                _OPTIMAL[key] = optimal_offsets(self.line)
        return _OPTIMAL[key]

    def optimal_at(self, progress: float) -> float | None:
        off = self.optimal(compute=False)
        return off[self.index_at(progress)] if off else None

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

    def geometry(self, step_m: float = 3.0, compute_optimal: bool = True) -> dict[str, Any]:
        """Downsampled shape for the dashboard. ``optimal`` (the optimal racing
        line) is empty without track edges, or when ``compute_optimal`` is False
        and it hasn't been worked out yet."""
        line = self.line
        idx = [0]
        for i in range(1, len(line)):
            if line.dist[i] - line.dist[idx[-1]] >= step_m:
                idx.append(i)
        left, right = line.edges() if self.has_edges else ([], [])
        off = self.optimal(compute=compute_optimal)
        opt = offsets_to_points(line, off) if off else []
        r2 = lambda v: round(v, 1)
        return {
            "track_key": self.track_key,
            "length_m": round(self.length_m, 1),
            "source": self.source,
            "has_edges": self.has_edges,
            "progress": [round(self.progress_of(i), 5) for i in idx],
            "center": [[r2(line.x[i]), r2(line.z[i])] for i in idx],
            "left": [[r2(left[i][0]), r2(left[i][1])] for i in idx] if left else [],
            "right": [[r2(right[i][0]), r2(right[i][1])] for i in idx] if right else [],
            "optimal": [[r2(opt[i][0]), r2(opt[i][1])] for i in idx] if opt else [],
            "corners": [c.to_dict() for c in self.corners],
            "sections": [asdict(s) for s in self.sections],
            "chapters": [c.to_dict() for c in self.chapters],
            "practice": [p.to_dict() for p in self.practice],
        }


# -- corner detection ------------------------------------------------------------


def _signed_curvature(line: TrackLine, window_m: float = 12.0) -> list[float]:
    """1/radius along the line; positive = right-hand turn (AC's world)."""
    n = len(line)
    spacing = line.length / max(1, n - 1)
    k = max(2, round(window_m / max(spacing, 0.1)))
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
    sign = lambda i: (1 if curv[i] > 0 else -1) if abs(curv[i]) > thr else 0

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
        prog = lambda i: line.dist[i] / line.length
        entry_p, exit_p = prog(idx[0]), prog(idx[-1])
        if exit_p < entry_p:  # runs over the start line: end it at the line
            exit_p = 0.99999
        corners.append(
            Corner(
                number=0,
                name="",
                direction="R" if s > 0 else "L",
                grade=grade_for_radius(radius),
                entry=entry_p,
                apex=min(max(prog(apex), entry_p), exit_p),
                exit=exit_p,
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
                # "Pflanzgarten 1" + 2nd corner → "Pflanzgarten 1b", not "Pflanzgarten 1 2"
                c.name = f"{c.name}{'abcdefgh'[k - 1]}" if c.name[-1].isdigit() else f"{c.name} {k}"
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


# -- practice sections -------------------------------------------------------------


@dataclass
class PracticeSection:
    """A stretch worth practising as one piece: a corner, or a complex of
    corners that are driven together (Les Combes 1-2-3, a chicane, an S-bend)."""

    number: int
    name: str
    corners: list[int]  # corner numbers
    start: float  # lap progress, a little before the first braking zone
    end: float  # a little after the last exit

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _base_name(name: str) -> str:
    """'Les Combes 2' → 'Les Combes', 'Pflanzgarten 1b' → 'Pflanzgarten 1'."""
    import re

    if not name:
        return ""
    m = re.match(r"^(.*?\d)[a-h]$", name)
    if m:
        return m.group(1)
    m = re.match(r"^(.*\D)\s+\d+$", name)
    return m.group(1).strip() if m else name


def practice_sections(
    corners: list[Corner],
    length_m: float,
    join_gap_m: float = 120.0,
    lead_m: float = 150.0,
    tail_m: float = 60.0,
    max_len_m: float = 800.0,
) -> list[PracticeSection]:
    """Group corners into sections: same name family, or so close together
    that the exit of one is the entry of the next."""
    if not corners or length_m <= 0:
        return []
    groups: list[list[Corner]] = [[corners[0]]]
    for c in corners[1:]:
        prev = groups[-1][-1]
        gap = ((c.entry - prev.exit) % 1.0) * length_m
        same_family = bool(c.name) and _base_name(c.name) == _base_name(prev.name)
        if gap <= join_gap_m or same_family:
            groups[-1].append(c)
        else:
            groups.append([c])
    # A complex that runs over the start line wraps into the first group.
    if len(groups) > 1:
        first, last = groups[0][0], groups[-1][-1]
        gap = ((first.entry - last.exit) % 1.0) * length_m
        if gap <= join_gap_m:
            groups[0] = groups.pop() + groups[0]

    # Long runs of linked corners (the Nordschleife has plenty) are split at
    # their biggest straight until each piece is a practicable length.
    def span(g: list[Corner]) -> float:
        return ((g[-1].exit - g[0].entry) % 1.0) * length_m

    def split(g: list[Corner]) -> list[list[Corner]]:
        if len(g) < 2 or span(g) <= max_len_m:
            return [g]
        gaps = [((g[k + 1].entry - g[k].exit) % 1.0) * length_m for k in range(len(g) - 1)]
        k = max(range(len(gaps)), key=gaps.__getitem__)
        return split(g[: k + 1]) + split(g[k + 1 :])

    groups = [piece for g in groups for piece in split(g)]

    out = []
    for i, g in enumerate(groups, 1):
        names = []
        for c in g:
            b = _base_name(c.name) or f"Turn {c.number}"
            if b not in names:
                names.append(b)
        if len(names) == 1:
            name = names[0] if g[0].name else (f"Turn {g[0].number}" if len(g) == 1 else f"Turns {g[0].number}–{g[-1].number}")
        else:
            name = f"{names[0]} to {names[-1]}"
        out.append(
            PracticeSection(
                number=i,
                name=name,
                corners=[c.number for c in g],
                start=(g[0].entry - lead_m / length_m) % 1.0,
                end=(g[-1].exit + tail_m / length_m) % 1.0,
            )
        )
    return out
