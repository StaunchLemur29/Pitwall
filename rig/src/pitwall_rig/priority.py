"""Keep Pitwall smooth while Assetto Corsa is using the PC.

AC takes all the CPU it can get. At normal priority Windows shares what's left
evenly with everything else, so the side-screen map (Chrome) and the service
feeding it get starved and stutter on heavy tracks. Two things help:

- Above-normal priority for the service and for every process of the windows
  Pitwall opened (Chrome's browser, GPU and page processes). They only use a
  little CPU, so this costs the game almost nothing, but when they do need it
  they get it first.
- Opting those processes out of Windows' power throttling ("efficiency mode",
  EcoQoS), which Windows 11 and Chrome put on windows that don't have focus.
  The game always has focus, so the side screen would otherwise be slowed.

Chrome starts new processes as it goes (a page process per window, a new GPU
process after a driver hiccup) and can lower them again, so the windows'
processes are boosted again every few seconds. Windows only; elsewhere this does nothing.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)

EVERY_S = 5.0


def descendants(pairs: Iterable[tuple[int, int]], root: int) -> list[int]:
    """``root`` and every process below it, from (pid, parent pid) pairs."""
    children: dict[int, list[int]] = defaultdict(list)
    for pid, ppid in pairs:
        if pid != ppid:  # the idle process is its own parent
            children[ppid].append(pid)
    out, todo, seen = [], [root], {root}
    while todo:
        pid = todo.pop()
        out.append(pid)
        for c in children.get(pid, []):
            if c not in seen:
                seen.add(c)
                todo.append(c)
    return out


# --- Windows ---------------------------------------------------------------

ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
POWER_THROTTLING_EXECUTION_SPEED = 0x1


def _process_pairs() -> list[tuple[int, int]]:
    """(pid, parent pid) for every running process."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out: list[tuple[int, int]] = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def _boost_handle(k32, handle) -> bool:
    import ctypes
    from ctypes import wintypes

    ok = bool(k32.SetPriorityClass(handle, ABOVE_NORMAL_PRIORITY_CLASS))

    class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

    # Take charge of execution-speed throttling and turn it off (Windows 10 1709+).
    set_info = getattr(k32, "SetProcessInformation", None)
    if set_info is not None:
        st = PROCESS_POWER_THROTTLING_STATE(1, POWER_THROTTLING_EXECUTION_SPEED, 0)
        set_info(handle, PROCESS_POWER_THROTTLING, ctypes.byref(st), ctypes.sizeof(st))
    return ok


def boost_pid(pid: int) -> bool:
    """Above-normal priority and no power throttling for one process."""
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        return _boost_handle(k32, ctypes.c_void_p(h))
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def boost_self() -> bool:
    """Boost the Pitwall service itself. False when not on Windows or it failed."""
    if sys.platform != "win32":
        return False
    import os

    try:
        ok = boost_pid(os.getpid())
    except (OSError, AttributeError):
        ok = False
    if ok:
        log.info("Running at above-normal priority, so the game can't starve Pitwall")
    return ok


class Keeper:
    """Boosts the processes of Pitwall's windows every few seconds.

    ``roots``: the pids of the browsers Pitwall started (the windows that are
    open now). ``pairs`` and ``boost`` are only swapped out in tests."""

    def __init__(
        self,
        roots: Callable[[], list[int]],
        pairs: Callable[[], list[tuple[int, int]]] = _process_pairs,
        boost: Callable[[int], bool] = boost_pid,
    ) -> None:
        self._roots, self._pairs, self._boost = roots, pairs, boost
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def tick(self) -> int:
        """Boost every process of the open windows. Returns how many took it.

        All of them every time, not just new ones: Chrome can lower a page
        process again when it thinks the window is in the background."""
        roots = self._roots()
        if not roots:
            return 0
        pairs = self._pairs()
        n = 0
        for pid in {pid for root in roots for pid in descendants(pairs, root)}:
            try:
                n += bool(self._boost(pid))
            except OSError:
                pass
        return n

    def start(self) -> None:
        if self._thread is not None or sys.platform != "win32":
            return

        def run() -> None:
            while not self._stop.wait(EVERY_S):
                try:
                    self.tick()
                except Exception:  # never take the service down over this
                    log.debug("Couldn't boost the windows' priority", exc_info=True)

        self._thread = threading.Thread(target=run, name="priority", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
