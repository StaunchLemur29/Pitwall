"""Open Pitwall windows in Chrome (or Edge) on the right monitor."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import default_data_dir
from .monitors import Monitor, list_monitors, pick_dashboard_monitor

log = logging.getLogger(__name__)


def _browser(which: str) -> str | None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = {
        "edge": [
            shutil.which("msedge"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            shutil.which("chrome"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            str(local / "Google" / "Chrome" / "Application" / "chrome.exe"),  # per-user install
        ],
    }
    for name in ["chrome", "edge"] if which == "auto" else [which]:
        for exe in candidates.get(name, []):
            if exe and Path(exe).exists():
                return exe
    return None


def _launch(url: str, display: dict[str, Any], x: int, y: int, w: int, h: int, profile: str, extra: list[str]) -> bool:
    exe = _browser(display.get("browser", "auto"))
    if exe is None:
        log.warning("Couldn't find Chrome or Edge; open %s yourself.", url)
        return False
    # Each window type gets its own browser profile, so Chrome honours the
    # position flags instead of handing the URL to an already-open window.
    subprocess.Popen(
        [
            exe,
            f"--app={url}",
            f"--window-position={x},{y}",
            f"--window-size={w},{h}",
            f"--user-data-dir={default_data_dir() / profile}",
            "--no-first-run",
            # The game has focus, so Chrome would otherwise treat our window as
            # "in the background" and slow it to a crawl.
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            *extra,
        ]
    )
    return True


def open_dashboard(url: str, display: dict[str, Any]) -> bool:
    """Full-screen on the vertical monitor."""
    x, y, w, h = display["window_x"], display["window_y"], 1080, 1920
    if display.get("monitor", "auto") == "auto":
        mon = pick_dashboard_monitor(list_monitors())
        if mon is not None:
            x, y, w, h = mon.x, mon.y, mon.width, mon.height
            log.info("Opening the dashboard on the %dx%d monitor at (%d, %d)", w, h, x, y)
        else:
            log.info("Only one monitor found; opening the dashboard on it")
    return _launch(url, display, x, y, w, h, "browser-profile", ["--start-fullscreen"])


def main_monitor(monitors: list[Monitor]) -> Monitor | None:
    return next((m for m in monitors if m.primary), monitors[0] if monitors else None)


def open_analysis(base_url: str, display: dict[str, Any]) -> bool:
    """A normal (maximised) window on the main screen with the analysis page."""
    mon = main_monitor(list_monitors())
    x, y, w, h = (mon.x, mon.y, mon.width, mon.height) if mon else (0, 0, 1600, 900)
    log.info("Opening analysis on the main screen")
    return _launch(base_url + "#/analysis", display, x + 40, y + 40, w - 80, h - 120, "browser-profile-analysis",
                   ["--start-maximized"])
