"""Read Assetto Corsa's own track files: the AI line with track edges, and named sections.

``ai/fast_lane.ai`` (version 7) layout, little-endian:

    int32 version, count, lap_time, sample_count
    count × { float x, y, z, length; int32 id }          # the AI racing line
    int32 extra_count
    extra_count × 18 floats:
        speed, gas, brake, obsolete_lat_g, radius,
        side_left, side_right,                            # metres to each track edge
        camber, direction, normal[3], length, forward[3], tag, grade
    ...                                                   # newer builds append more; ignored

Verified against a real track (Spa 2022 mod): 4470 points ~1.55 m apart,
side_left/right ≈ 5–10 m.
"""

from __future__ import annotations

import configparser
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrackLine:
    """The AI line plus track edges, sampled along the lap."""

    x: list[float]
    y: list[float]
    z: list[float]
    dist: list[float]  # metres from the start line
    side_left: list[float]
    side_right: list[float]
    speed: list[float] = field(default_factory=list)  # AI speed, m/s

    @property
    def length(self) -> float:
        return self.dist[-1] if self.dist else 0.0

    def __len__(self) -> int:
        return len(self.x)

    def normal(self, i: int) -> tuple[float, float]:
        """Unit vector (x, z) pointing to the driver's left at point i."""
        n = len(self.x)
        a, b = (i - 1) % n, (i + 1) % n
        dx, dz = self.x[b] - self.x[a], self.z[b] - self.z[a]
        d = math.hypot(dx, dz) or 1.0
        # Left of heading (dx, dz) in AC's world is (dz, -dx). Checked on real
        # data: at corner apexes the AI line sits closest to the inside edge,
        # and a recorded lap stays between the edges with this convention.
        return (dz / d, -dx / d)

    def edges(self) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Left and right track edges as (x, z) points."""
        left, right = [], []
        for i in range(len(self.x)):
            nx, nz = self.normal(i)
            left.append((self.x[i] + nx * self.side_left[i], self.z[i] + nz * self.side_left[i]))
            right.append((self.x[i] - nx * self.side_right[i], self.z[i] - nz * self.side_right[i]))
        return left, right


@dataclass
class Section:
    name: str
    start: float  # lap progress 0..1
    end: float


def read_fast_lane(path: Path | str) -> TrackLine:
    b = Path(path).read_bytes()
    version, count, _lap_time, _samples = struct.unpack_from("<4i", b, 0)
    if version < 7:
        raise ValueError(f"{path}: AI line version {version} has no track-edge data")
    off = 16
    xs, ys, zs, ds = [], [], [], []
    for i in range(count):
        x, y, z, d, _id = struct.unpack_from("<4fi", b, off + i * 20)
        xs.append(x)
        ys.append(y)
        zs.append(z)
        ds.append(d)
    off += count * 20
    (extra,) = struct.unpack_from("<i", b, off)
    off += 4
    if extra != count:
        raise ValueError(f"{path}: expected {count} extra records, found {extra}")
    left, right, speed = [], [], []
    for i in range(count):
        rec = struct.unpack_from("<18f", b, off + i * 72)
        speed.append(rec[0])
        left.append(rec[5])
        right.append(rec[6])
    return TrackLine(xs, ys, zs, ds, left, right, speed)


def read_sections(path: Path | str) -> list[Section]:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.read(path, encoding="utf-8-sig")
    out = []
    for name in cp.sections():
        sec = cp[name]
        try:
            out.append(Section(sec.get("TEXT", name).strip(), float(sec["IN"]), float(sec["OUT"])))
        except (KeyError, ValueError):
            continue
    return sorted(out, key=lambda s: s.start)


def lateral_position(line: TrackLine, x: float, z: float, hint: int | None = None) -> tuple[int, float, float]:
    """Where a car is across the track.

    Returns (nearest line index, metres left of the AI line (negative = right),
    fraction across the track from the left edge 0.0 to the right edge 1.0).
    ``hint`` (the previous index) keeps the search local and fast.
    """
    n = len(line)
    if hint is None:
        candidates = range(n)
    else:
        candidates = (j % n for j in range(hint - 40, hint + 80))
    best_i, best_d = 0, float("inf")
    for i in candidates:
        d = (line.x[i] - x) ** 2 + (line.z[i] - z) ** 2
        if d < best_d:
            best_i, best_d = i, d
    nx, nz = line.normal(best_i)
    offset = (x - line.x[best_i]) * nx + (z - line.z[best_i]) * nz
    width = line.side_left[best_i] + line.side_right[best_i]
    frac = (line.side_left[best_i] - offset) / width if width > 0 else 0.5
    return best_i, offset, frac
