"""Track packs: hand-written knowledge layered on top of the game's data.

A pack is a JSON file here. ``match`` lists substrings of the track folder name.
Chapters name the game section where they begin; each runs until the next one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any

from ..tracks.ac_files import Section


@dataclass
class Chapter:
    number: int
    name: str
    summary: str
    start: float  # lap progress
    end: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def load_packs() -> list[dict[str, Any]]:
    out = []
    for f in resources.files(__package__).iterdir():
        if f.name.endswith(".json"):
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def find_pack(track: str) -> dict[str, Any] | None:
    t = track.lower()
    return next((p for p in load_packs() if any(m in t for m in p.get("match", []))), None)


def resolve_chapters(pack: dict[str, Any], sections: list[Section]) -> list[Chapter]:
    """Turn chapter definitions into progress ranges using this layout's sections.
    Chapters whose start section this layout doesn't have are skipped."""
    by_name = {_norm(s.name): s for s in sections}
    starts = []
    for ch in pack.get("chapters", []):
        sec = by_name.get(_norm(ch["from"]))
        if sec is not None:
            starts.append((sec.start, ch))
    starts.sort(key=lambda x: x[0])
    chapters = []
    for i, (start, ch) in enumerate(starts):
        if i + 1 < len(starts):
            end = starts[i + 1][0]
        else:  # the last chapter runs over the line into the first one
            first = starts[0][0]
            end = first if first > 0.002 else 0.99999
        chapters.append(Chapter(i + 1, ch["name"], ch.get("summary", ""), start, end))
    return chapters
