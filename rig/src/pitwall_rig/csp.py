"""Link to Pitwall's in-game CSP app (csp/Pitwall in the repo).

The app runs inside Assetto Corsa and talks to the rig over local HTTP:

* every ~100 ms it POSTs ``/api/csp/sync`` with what only CSP knows (the real
  ABS / TC levels, brake bias, whether car resets are allowed) plus results of
  commands, and gets back the drill, the track version and pending commands;
* when the track version changes it GETs ``/api/csp/track``: corners, braking
  points and the reference lap's speed profile, so it can work out the next
  corner and brake countdown itself, every frame, with no lag.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

FRESH_S = 2.0  # the app counts as connected if it synced this recently


class CspLink:
    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self.state: dict[str, Any] = {}
        self.synced_at: float | None = None
        self._commands: list[dict[str, Any]] = []
        self.version = 0  # bumped whenever the track data the app holds is out of date

    # -- the app's side -----------------------------------------------------

    def sync(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """Store what the app reports; return its events and hand over pending commands."""
        self.synced_at = self._clock()
        self.state = {k: body.get(k) for k in ("abs", "abs_modes", "tc", "tc_modes", "bb", "reset_allowed",
                                               "has_launch", "app_version")}
        events = [e for e in body.get("events") or [] if isinstance(e, dict)]
        return events

    def take_commands(self) -> list[dict[str, Any]]:
        out, self._commands = self._commands, []
        return out

    # -- the rig's side -----------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.synced_at is not None and self._clock() - self.synced_at < FRESH_S

    @property
    def can_reset(self) -> bool:
        return self.connected and bool(self.state.get("reset_allowed"))

    def send(self, cmd: dict[str, Any]) -> None:
        self._commands.append(cmd)

    def touch(self) -> None:
        """The track or reference changed: the app should fetch it again."""
        self.version += 1

    def electronics(self) -> dict[str, Any] | None:
        """Real ABS / TC levels and brake bias from CSP, while the app is connected."""
        if not self.connected:
            return None
        s = self.state
        return {
            "abs": s.get("abs"),
            "abs_modes": s.get("abs_modes"),
            "tc": s.get("tc"),
            "tc_modes": s.get("tc_modes"),
            "bb": s.get("bb"),
        }


# -- installing the app into Assetto Corsa ---------------------------------------

APP_SOURCE = Path(__file__).resolve().parents[3] / "csp" / "Pitwall"


def install_app(ac_root: Path, source: Path = APP_SOURCE) -> str:
    """Copy the in-game app to ``<AC>/apps/lua/Pitwall`` if it's missing or out of date.

    Returns "installed", "updated", "up to date" or "no source".
    """
    if not source.is_dir():
        return "no source"
    dest = ac_root / "apps" / "lua" / source.name
    existed = dest.is_dir()
    changed = False
    dest.mkdir(parents=True, exist_ok=True)
    for f in source.iterdir():
        if not f.is_file():
            continue
        target = dest / f.name
        data = f.read_bytes()
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
            changed = True
    if not existed:
        return "installed"
    return "updated" if changed else "up to date"
