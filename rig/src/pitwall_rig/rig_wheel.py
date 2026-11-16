"""The SF1000 wheel screen (F1 23 UDP over Wi-Fi).

A part of the Rig (rig.py): its methods use the Rig's state."""

from __future__ import annotations

import logging
from typing import Any

from .models import Frame

log = logging.getLogger(__name__)


class WheelMixin:
    def _wheel(self) -> Any:
        """The SF1000 sender for the address in Settings (None when it's off)."""
        cfg = self.config["sf1000"]
        if not cfg.get("enabled") or not cfg.get("ip"):
            self.sf1000 = None
            return None
        addr = (cfg["ip"], int(cfg.get("port") or 20777))
        if self.sf1000 is None or self.sf1000.addr != addr:
            from .sf1000 import Sf1000

            self.sf1000 = Sf1000(*addr)
        return self.sf1000

    def _feed_wheel(self, frame: Frame) -> None:
        wheel = self._wheel()
        if wheel is not None:
            wheel.send(frame, self.session)

    def sf1000_status(self) -> dict[str, Any]:
        w = self.sf1000
        return {"enabled": w is not None, "sent": w.sent if w else 0, "error": w.error if w else None}

    def sf1000_test(self, ip: str | None = None) -> dict[str, Any]:
        """Sweep rev lights, gears and speed on the wheel to show the link works."""
        from .sf1000 import Sf1000

        target = ip or self.config["sf1000"].get("ip")
        if not target:
            return {"ok": False, "error": "Put in the wheel's IP first (on its Wi-Fi page)."}
        w = Sf1000(target, int(self.config["sf1000"].get("port") or 20777))
        w.test_pattern(self.session)
        return {"ok": w.error is None, "sent": w.sent, "error": w.error}
