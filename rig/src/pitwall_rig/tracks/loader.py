"""Build a TrackModel for the current session: from the game's files when we
can, otherwise from your own laps."""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import SessionInfo
from .ac_files import TrackLine, read_fast_lane, read_sections
from .ac_install import find_ac_root, track_files
from ..packs import find_pack, resolve_chapters
from .model import TrackModel, detect_corners

log = logging.getLogger(__name__)


def from_ac_files(ac_root: Path, session: SessionInfo) -> TrackModel | None:
    files = track_files(ac_root, session.track, session.track_config)
    if files.fast_lane is None:
        log.info("No AI line for %s; the map will be learnt from your laps", session.track_key)
        return None
    try:
        line = read_fast_lane(files.fast_lane)
    except (ValueError, OSError) as e:
        log.warning("Couldn't read %s: %s", files.fast_lane, e)
        return None
    sections = read_sections(files.sections) if files.sections else []
    corners = detect_corners(line, sections)
    log.info(
        "Track %s: %.0f m, %d corners, %d named sections (from the game's files)",
        session.track_key, line.length, len(corners), len(sections),
    )
    model = TrackModel(session.track_key, line.length, line, corners, sections, source="game")
    pack = find_pack(session.track)
    if pack is not None:
        model.chapters = resolve_chapters(pack, sections)
        log.info("Track pack %r: %d chapters", pack.get("name"), len(model.chapters))
    return model


def from_lap_trace(track_key: str, trace: dict[str, list[float]], length_m: float) -> TrackModel | None:
    """Fallback: use a driven lap as the centre line (no track edges)."""
    xs, zs, ps = trace.get("x", []), trace.get("z", []), trace.get("p", [])
    pts = [(x, z, p) for x, z, p, t in zip(xs, zs, ps, trace.get("t", []), strict=False) if not (t < 5 and p > 0.9)]
    pts.sort(key=lambda q: q[2])
    if len(pts) < 50:
        return None
    length = length_m
    if not length:
        length = sum(
            ((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2) ** 0.5 for i in range(1, len(pts))
        )
    line = TrackLine(
        x=[q[0] for q in pts],
        y=[0.0] * len(pts),
        z=[q[1] for q in pts],
        dist=[q[2] * length for q in pts],
        side_left=[0.0] * len(pts),
        side_right=[0.0] * len(pts),
    )
    return TrackModel(track_key, length, line, detect_corners(line), [], source="laps", has_edges=False)


class TrackLoader:
    def __init__(self, ac_install_dir: str = "") -> None:
        self._configured = ac_install_dir
        self._ac_root: Path | None = None
        self._searched = False
        self._cache: dict[str, TrackModel] = {}

    @property
    def ac_root(self) -> Path | None:
        if not self._searched:
            self._searched = True
            self._ac_root = find_ac_root(self._configured)
            log.info("Assetto Corsa install: %s", self._ac_root or "not found (set it in Settings)")
        return self._ac_root

    def load(self, session: SessionInfo) -> TrackModel | None:
        key = f"{session.game}:{session.track_key}"
        if key in self._cache:
            return self._cache[key]
        model = None
        if session.game == "ac" and self.ac_root is not None:
            model = from_ac_files(self.ac_root, session)
        if model is not None:
            self._cache[key] = model
        return model
