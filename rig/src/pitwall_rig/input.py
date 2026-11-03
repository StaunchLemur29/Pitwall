"""Wheel buttons/axes and global keyboard shortcuts → dashboard actions.

Works while the game has focus:
- Joysticks via SDL2 (pygame-ce) with background events enabled. The SF1000's
  buttons, encoders and paddles show up on the wheel base's device.
- Keyboard via pynput global hotkeys (fallback for rims without spare buttons).

Both libraries are optional (``pip install pitwall-rig[input]``). Without them
the service logs a note and actions can still be triggered from the dashboard.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

AXIS_THRESHOLD = 0.5  # how far from rest an axis must move to count as "pressed"


@dataclass(frozen=True)
class InputEvent:
    """A raw press, before it is matched to an action."""

    type: str  # "button" | "axis"
    device: str  # SDL GUID
    device_name: str
    index: int
    rest: float = 0.0
    direction: int = 1
    pressed: bool = True  # False when the button/paddle is let go

    def as_binding(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.type,
            "device": self.device,
            "device_name": self.device_name,
            "index": self.index,
        }
        if self.type == "axis":
            d["rest"] = round(self.rest, 2)
            d["direction"] = self.direction
        return d


def matches(binding: dict[str, Any], ev: InputEvent) -> bool:
    if binding.get("type") != ev.type or binding.get("index") != ev.index:
        return False
    if binding.get("device") and binding["device"] == ev.device:
        pass
    elif binding.get("device_name") != ev.device_name:
        return False
    if ev.type == "axis":
        return int(binding.get("direction", 1)) == ev.direction
    return True


class InputService:
    """Runs input polling in background threads and reports actions."""

    def __init__(
        self,
        get_bindings: Callable[[], dict[str, list[dict[str, Any]]]],
        on_action: Callable[[str, bool], None],
        on_raw: Callable[[InputEvent], None] | None = None,
    ) -> None:
        self._get_bindings = get_bindings
        self._on_action = on_action
        self._on_raw = on_raw
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._hotkeys: Any = None
        self.devices: list[dict[str, str]] = []
        self.joystick_available = False
        self.keyboard_available = False

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        t = threading.Thread(target=self._joystick_loop, name="pitwall-joystick", daemon=True)
        t.start()
        self._threads.append(t)
        self.reload_keyboard()

    def stop(self) -> None:
        self._stop.set()
        if self._hotkeys is not None:
            self._hotkeys.stop()

    # -- dispatch -----------------------------------------------------------

    def handle(self, ev: InputEvent) -> None:
        """Presses and releases both reach the rig; most actions only use presses,
        hold actions (like rewind) use both."""
        if self._on_raw is not None and ev.pressed:
            self._on_raw(ev)
        for action, binds in self._get_bindings().items():
            if any(matches(b, ev) for b in binds):
                self._on_action(action, ev.pressed)

    # -- keyboard -----------------------------------------------------------

    def reload_keyboard(self) -> None:
        try:
            from pynput import keyboard  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001 - optional dependency / no display
            log.info("Keyboard shortcuts disabled (install pitwall-rig[input] to enable).")
            return
        if self._hotkeys is not None:
            self._hotkeys.stop()
        mapping: dict[str, Callable[[], None]] = {}
        for action, binds in self._get_bindings().items():
            for b in binds:
                if b.get("type") == "key" and b.get("combo"):
                    mapping[b["combo"]] = (lambda a=action: self._on_action(a, True))
        if not mapping:
            return
        try:
            self._hotkeys = keyboard.GlobalHotKeys(mapping)
            self._hotkeys.start()
            self.keyboard_available = True
        except Exception as e:  # noqa: BLE001
            log.warning("Could not register keyboard shortcuts: %s", e)

    # -- joystick -----------------------------------------------------------

    def _joystick_loop(self) -> None:
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001
            log.info("Wheel input disabled (install pitwall-rig[input] to enable).")
            return
        try:
            pygame.display.init()
            pygame.joystick.init()
        except Exception as e:  # noqa: BLE001
            log.warning("Wheel input unavailable: %s", e)
            return
        self.joystick_available = True
        sticks: dict[int, Any] = {}
        rest: dict[tuple[int, int], float] = {}
        held: set[tuple[int, int, int]] = set()

        def refresh() -> None:
            sticks.clear()
            for i in range(pygame.joystick.get_count()):
                js = pygame.joystick.Joystick(i)
                js.init()
                sticks[js.get_instance_id()] = js
                for a in range(js.get_numaxes()):
                    rest[(js.get_instance_id(), a)] = js.get_axis(a)
            self.devices = [{"guid": j.get_guid(), "name": j.get_name()} for j in sticks.values()]
            log.info("Input devices: %s", ", ".join(d["name"] for d in self.devices) or "none")

        refresh()
        while not self._stop.is_set():
            for e in pygame.event.get():
                if e.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    refresh()
                elif e.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                    js = sticks.get(e.instance_id)
                    if js is not None:
                        self.handle(
                            InputEvent(
                                "button", js.get_guid(), js.get_name(), e.button,
                                pressed=e.type == pygame.JOYBUTTONDOWN,
                            )
                        )
                elif e.type == pygame.JOYAXISMOTION:
                    js = sticks.get(e.instance_id)
                    if js is None:
                        continue
                    r = rest.get((e.instance_id, e.axis), 0.0)
                    moved = e.value - r
                    direction = 1 if moved > 0 else -1
                    key = (e.instance_id, e.axis, direction)
                    if abs(moved) >= AXIS_THRESHOLD and key not in held:
                        held.add(key)
                        self.handle(
                            InputEvent("axis", js.get_guid(), js.get_name(), e.axis, r, direction)
                        )
                    elif abs(moved) < AXIS_THRESHOLD / 2:
                        for d in (1, -1):
                            k = (e.instance_id, e.axis, d)
                            if k in held:
                                held.discard(k)
                                self.handle(
                                    InputEvent("axis", js.get_guid(), js.get_name(), e.axis, r, d, pressed=False)
                                )
            time.sleep(0.005)


# Scan codes (set 1). Games often ignore synthetic key presses unless they're sent
# as scan codes, so on Windows we use SendInput with KEYEVENTF_SCANCODE.
# (code, extended)
_SCAN: dict[str, tuple[int, bool]] = {
    "insert": (0x52, True), "delete": (0x53, True), "home": (0x47, True), "end": (0x4F, True),
    "page_up": (0x49, True), "page_down": (0x51, True),
    "up": (0x48, True), "down": (0x50, True), "left": (0x4B, True), "right": (0x4D, True),
    "backspace": (0x0E, False), "tab": (0x0F, False), "enter": (0x1C, False), "space": (0x39, False),
    "pause": (0x45, False), "scroll_lock": (0x46, False),
    **{f"f{i}": (0x3B + i - 1, False) for i in range(1, 11)},
    "f11": (0x57, False), "f12": (0x58, False),
    **{f"f{i}": (0x64 + i - 13, False) for i in range(13, 24)}, "f24": (0x76, False),
    **{c: (code, False) for c, code in zip("1234567890", [0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B])},
    **{c: (code, False) for c, code in zip(
        "qwertyuiop", [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19])},
    **{c: (code, False) for c, code in zip("asdfghjkl", [0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26])},
    **{c: (code, False) for c, code in zip("zxcvbnm", [0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32])},
}


def _send_scancode(code: int, extended: bool, up: bool) -> bool:
    """Windows SendInput with a hardware scan code. Returns False elsewhere."""
    import sys

    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    flags = 0x0008 | (0x0001 if extended else 0) | (0x0002 if up else 0)  # SCANCODE|EXTENDED|KEYUP
    inp = INPUT(type=1, u=_U(ki=KEYBDINPUT(0, code, flags, 0, 0)))
    return ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1


class KeyHolder:
    """Holds a keyboard key down for as long as needed (goes to the focused
    window, i.e. the game). Used for Time Shift, which rewinds while its key is held.

    Windows: hardware scan codes via SendInput (what games listen to).
    Elsewhere / unknown keys: pynput. A safety timer always lets go after ``max_hold_s``.
    """

    def __init__(self, max_hold_s: float = 20.0) -> None:
        self._held: tuple[str, Any] | None = None  # ("scan", (code, ext)) | ("pynput", key)
        self._kb: Any = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._max = max_hold_s

    @property
    def holding(self) -> bool:
        return self._held is not None

    def _press(self, name: str) -> tuple[str, Any] | None:
        sc = _SCAN.get(name.lower())
        if sc is not None and _send_scancode(sc[0], sc[1], up=False):
            return ("scan", sc)
        try:
            from pynput.keyboard import Controller, Key  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001
            log.warning("Can't press keys on this system.")
            return None
        if self._kb is None:
            self._kb = Controller()
        key = getattr(Key, name.lower(), None) if len(name) > 1 else name
        if key is None:
            log.warning("Unknown key name %r", name)
            return None
        self._kb.press(key)
        return ("pynput", key)

    def down(self, name: str) -> bool:
        with self._lock:
            if self._held is not None:
                return True
            held = self._press(name)
            if held is None:
                return False
            self._held = held
            self._timer = threading.Timer(self._max, self.up)
            self._timer.daemon = True
            self._timer.start()
            return True

    def up(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._held is not None:
                kind, what = self._held
                if kind == "scan":
                    _send_scancode(what[0], what[1], up=True)
                elif self._kb is not None:
                    self._kb.release(what)
            self._held = None
