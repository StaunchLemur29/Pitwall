"""User settings: a JSON file merged over built-in defaults.

Everything the user might want to change lives here, and the dashboard's
settings page edits it, so nothing needs a code change.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

#: Widgets the dashboard knows. ``phase`` marks ones that are placeholders until then.
WIDGETS: dict[str, dict[str, Any]] = {
    "next_corner": {"label": "Next corner", "phase": 1},
    "turn_by_turn": {"label": "Road ahead (turn-by-turn)", "phase": 1},
    "lap_analysis": {"label": "Lap analysis", "phase": 1},
    "track_map": {"label": "Track map", "phase": 0},
    "drill": {"label": "Drill / focus", "phase": 1},
    "coach_tip": {"label": "Coach tip", "phase": 3},
    "electronics": {"label": "Electronics (BB / ABS / TC)", "phase": 0},
    "lap_times": {"label": "Lap times & delta", "phase": 0},
    "tyres": {"label": "Tyre pressures & temps", "phase": 0},
    "session_bar": {"label": "Session timer & music", "phase": 0},
    "recent_laps": {"label": "Recent laps", "phase": 0},
}

#: Things a wheel button / key can trigger.
ACTIONS: dict[str, str] = {
    "next_page": "Next dashboard page",
    "prev_page": "Previous dashboard page",
    "mark_corner": "Mark this spot on the track",
    "drill_here": "Start a drill on the next corner",
    "stop_drill": "Stop the drill",
    "open_analysis": "Open analysis on the main screen",
    "rewind": "Rewind (presses your Time Shift key)",
}


def _w(widget: str, size: int = 1) -> dict[str, Any]:
    return {"widget": widget, "size": size}


DEFAULTS: dict[str, Any] = {
    "game": "ac",
    # Leave install_dir empty to find Assetto Corsa through Steam automatically.
    # rewind_key: the key Pitwall presses to trigger CSP's Time Shift rewind
    # (bind the same key inside Time Shift). rewind_hold_ms: hold it this long.
    "games": {"ac": {"install_dir": "", "rewind_key": "insert", "rewind_hold_ms": 120}},
    "server": {"host": "127.0.0.1", "port": 8765},
    "rates": {"poll_hz": 60, "broadcast_hz": 60},
    "laps": {"max_tyres_out": 2},
    "units": {"speed": "kmh", "pressure": "psi", "temperature": "c"},
    "display": {
        "accent": "#ff5a36",
        "open_browser": True,
        "browser": "auto",  # auto (Chrome, then Edge) | chrome | edge
        "monitor": "auto",  # auto = find the vertical monitor; manual = use window_x/window_y
        "window_x": 1920,  # manual only: top-left of the monitor in Windows' desktop coordinates
        "window_y": 0,
    },
    "session_timer": {"break_reminder_min": 0},
    # Each mode has pages; each page is a top-to-bottom stack of widgets.
    # "size" is the relative height share.
    "layouts": {
        "driving": [
            [
                _w("next_corner", 3),
                _w("turn_by_turn", 6),
                _w("drill", 2),
                _w("coach_tip", 1),
                _w("electronics", 2),
                _w("session_bar", 1),
            ],
            [_w("lap_times", 3), _w("track_map", 5), _w("tyres", 2), _w("session_bar", 1)],
        ],
        "analysis": [
            [_w("lap_times", 2), _w("lap_analysis", 10), _w("session_bar", 1)],
            [_w("recent_laps", 6), _w("track_map", 4), _w("session_bar", 1)],
        ],
    },
    # action -> list of bindings. Joystick: {"type": "button", "device": guid, "device_name": str,
    # "index": int} or {"type": "axis", ..., "index": int, "rest": float, "direction": 1|-1}.
    # Keyboard: {"type": "key", "combo": "<ctrl>+<alt>+n"}.
    "bindings": {
        "next_page": [{"type": "key", "combo": "<ctrl>+<alt>+<right>"}],
        "prev_page": [{"type": "key", "combo": "<ctrl>+<alt>+<left>"}],
        "mark_corner": [{"type": "key", "combo": "<ctrl>+<alt>+m"}],
    },
}


# Layouts shipped before phase 1. A saved config still holding exactly these
# gets the new defaults instead (so new widgets show up without a reset).
_OLD_DEFAULT_LAYOUTS = [
    {
        "driving": [
            [_w("next_corner", 3), _w("track_map", 4), _w("drill", 2), _w("coach_tip", 1),
             _w("electronics", 2), _w("session_bar", 1)],
            [_w("lap_times", 3), _w("track_map", 5), _w("tyres", 2), _w("session_bar", 1)],
        ],
        "analysis": [[_w("lap_times", 3), _w("recent_laps", 6), _w("track_map", 4), _w("session_bar", 1)]],
    },
]


def migrate(user: dict[str, Any]) -> dict[str, Any]:
    if user.get("layouts") in _OLD_DEFAULT_LAYOUTS:
        user = {k: v for k, v in user.items() if k != "layouts"}
    return user


def default_data_dir() -> Path:
    if env := os.environ.get("PITWALL_HOME"):
        return Path(env)
    if sys.platform == "win32" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / "Pitwall"
    return Path.home() / ".pitwall"


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "bindings":
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def diff_from(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k not in base:
            out[k] = v
        elif isinstance(v, dict) and isinstance(base[k], dict) and k != "bindings":
            sub = diff_from(base[k], v)
            if sub:
                out[k] = sub
        elif v != base[k]:
            out[k] = v
    return out


class ConfigError(ValueError):
    pass


def validate(cfg: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems (empty if fine)."""
    errs: list[str] = []
    if cfg.get("game") not in ("ac", "demo", "replay"):
        errs.append("game must be one of: ac, demo, replay")
    if cfg.get("display", {}).get("monitor") not in ("auto", "manual"):
        errs.append("display.monitor must be auto or manual")
    port = cfg.get("server", {}).get("port")
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        errs.append("server.port must be a number between 1024 and 65535")
    for key in ("poll_hz", "broadcast_hz"):
        v = cfg.get("rates", {}).get(key)
        if not isinstance(v, (int, float)) or not 1 <= v <= 120:
            errs.append(f"rates.{key} must be between 1 and 120")
    layouts = cfg.get("layouts", {})
    for mode in ("driving", "analysis"):
        pages = layouts.get(mode)
        if not isinstance(pages, list) or not pages:
            errs.append(f"layouts.{mode} needs at least one page")
            continue
        for pi, page in enumerate(pages):
            if not isinstance(page, list):
                errs.append(f"layouts.{mode}[{pi}] must be a list of widgets")
                continue
            for item in page:
                if not isinstance(item, dict) or item.get("widget") not in WIDGETS:
                    errs.append(f"layouts.{mode}[{pi}] has an unknown widget: {item!r}")
                elif not isinstance(item.get("size", 1), (int, float)) or item.get("size", 1) <= 0:
                    errs.append(f"layouts.{mode}[{pi}] {item['widget']} size must be positive")
    for action, binds in cfg.get("bindings", {}).items():
        if action not in ACTIONS:
            errs.append(f"bindings: unknown action {action!r}")
        elif not isinstance(binds, list):
            errs.append(f"bindings.{action} must be a list")
    return errs


class Config:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        if path.exists():
            try:
                user = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ConfigError(f"{path} is not valid JSON: {e}") from e
            self.data = deep_merge(DEFAULTS, migrate(user))
        errs = validate(self.data)
        if errs:
            raise ConfigError(f"Problems in {path}:\n  - " + "\n  - ".join(errs))
        if path.exists():
            self.save()  # tidy older files that stored every default

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def update(self, new: dict[str, Any]) -> list[str]:
        merged = deep_merge(DEFAULTS, new)
        errs = validate(merged)
        if errs:
            return errs
        self.data = merged
        self.save()
        return []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        # Only store what differs from the defaults, so improved defaults in
        # later versions still reach you.
        tmp.write_text(json.dumps(diff_from(DEFAULTS, self.data), indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def reset(self) -> None:
        self.data = copy.deepcopy(DEFAULTS)
        self.save()
