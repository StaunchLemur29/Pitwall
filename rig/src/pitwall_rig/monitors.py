"""Find the vertical monitor so the dashboard opens on it without any setup."""

from __future__ import annotations

import contextlib
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int
    primary: bool

    @property
    def portrait(self) -> bool:
        return self.height > self.width

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "portrait": self.portrait}


def list_monitors() -> list[Monitor]:
    """Monitors in Windows desktop coordinates. Empty on other platforms."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    with contextlib.suppress(Exception):  # report real pixels, not DPI-scaled ones
        ctypes.windll.shcore.SetProcessDpiAwareness(2)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    found: list[Monitor] = []
    proc_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def callback(hmon, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(Monitor(r.left, r.top, r.right - r.left, r.bottom - r.top, bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    return found


def pick_dashboard_monitor(monitors: list[Monitor]) -> Monitor | None:
    """A portrait monitor that isn't the main screen, else any non-main screen."""
    for test in (
        lambda m: m.portrait and not m.primary,
        lambda m: m.portrait,
        lambda m: not m.primary,
    ):
        for m in monitors:
            if test(m):
                return m
    return None
