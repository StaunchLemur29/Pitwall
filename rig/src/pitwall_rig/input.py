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
        on_action: Callable[[str], None],
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
        if self._on_raw is not None:
            self._on_raw(ev)
        for action, binds in self._get_bindings().items():
            if any(matches(b, ev) for b in binds):
                self._on_action(action)

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
                    mapping[b["combo"]] = (lambda a=action: self._on_action(a))
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
                elif e.type == pygame.JOYBUTTONDOWN:
                    js = sticks.get(e.instance_id)
                    if js is not None:
                        self.handle(InputEvent("button", js.get_guid(), js.get_name(), e.button))
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
                        held.discard((e.instance_id, e.axis, 1))
                        held.discard((e.instance_id, e.axis, -1))
            time.sleep(0.005)


def press_key(name: str, hold_s: float = 0.1) -> bool:
    """Press and release a key system-wide (goes to the focused window, i.e. the game).

    ``name`` is a pynput key name ("insert", "f13", "home") or a single character.
    Runs in a thread so the rig loop never waits for it.
    """
    try:
        from pynput.keyboard import Controller, Key  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        log.warning("Can't press keys (install pitwall-rig[input]).")
        return False
    key = getattr(Key, name.lower(), None) if len(name) > 1 else name
    if key is None:
        log.warning("Unknown key name %r for rewind", name)
        return False

    def go() -> None:
        kb = Controller()
        kb.press(key)
        time.sleep(max(0.02, hold_s))
        kb.release(key)

    threading.Thread(target=go, name="pitwall-keypress", daemon=True).start()
    return True
