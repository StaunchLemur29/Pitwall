"""Locate the Assetto Corsa install and a track layout's files."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


def find_ac_root(configured: str = "") -> Path | None:
    """The folder containing ``content/tracks``. ``configured`` wins if valid."""
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    for lib in _steam_libraries():
        candidates.append(lib / "steamapps" / "common" / "assettocorsa")
    candidates += [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa"),
        Path(r"C:\Program Files\Steam\steamapps\common\assettocorsa"),
    ]
    for c in candidates:
        if (c / "content" / "tracks").is_dir():
            return c
    return None


def _steam_libraries() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
        except OSError:
            pass
    if env := os.environ.get("STEAM_DIR"):
        roots.append(Path(env))
    libs: list[Path] = []
    for root in roots:
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


@dataclass
class TrackFiles:
    fast_lane: Path | None
    sections: Path | None
    corners: Path | None  # optional hand-made corner list (ai_corners.ini)


def track_files(ac_root: Path, track: str, layout: str) -> TrackFiles:
    """Files for one layout. Layout tracks keep ``ai``/``data`` in a subfolder;
    single-layout tracks keep them at the track root."""
    base = ac_root / "content" / "tracks" / track
    dirs = [base / layout, base] if layout else [base]

    def first(*rel: str) -> Path | None:
        for d in dirs:
            for r in rel:
                p = d / r
                if p.is_file():
                    return p
        return None

    return TrackFiles(
        fast_lane=first("ai/fast_lane.ai"),
        sections=first("data/sections.ini"),
        corners=first("data/ai_corners.ini"),
    )
