"""The pit report: how the stint went, built when you come into the pits.

A part of the Rig (rig.py): its methods use the Rig's state."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .models import Frame, GameStatus

log = logging.getLogger(__name__)


class PitsMixin:
    def _note_pits(self, f: Frame) -> None:
        """Coming into the pits: work out how the stint went. Leaving: a new stint."""
        if f.status != GameStatus.LIVE:
            return
        if self._stint_cond is None:
            self._stint_cond = self.conditions.snapshot(f)
        in_pits = f.in_pit_lane or f.in_pit_box
        p0, self._stint_p = getattr(self, "_stint_p", None), f.lap_progress
        if p0 is not None and 0 < (f.lap_progress - p0) % 1.0 < 0.01:
            self._stint_laps_driven = getattr(self, "_stint_laps_driven", 0.0) + (f.lap_progress - p0) % 1.0
        if not in_pits:
            # the car as it was out on track: "return to pits" resets it before we see the pits
            self._last_track_snap = self.conditions.snapshot(f)
        if in_pits and not self._in_pits:
            s = self.session
            if s is not None:
                end = getattr(self, "_last_track_snap", None) or self.conditions.snapshot(f)
                # in a moment: the lap you just finished (or left) is still being saved
                driven = getattr(self, "_stint_laps_driven", 0.0)
                threading.Timer(2.0, self._build_pit_report, args=(s.game, s.car, s.track_key, end, driven)).start()
        elif not in_pits and self._in_pits:
            self.pit_report = None
            self._stint_t0 = time.time()
            self._stint_laps_driven = 0.0
            self._stint_cond = self.conditions.snapshot(f)
        self._in_pits = in_pits

    def _build_pit_report(self, game: str, car: str, track_key: str, end: dict[str, Any] | None,
                          driven: float = 0.0) -> None:
        from .stint import stint_report

        try:
            laps = [x for x in self.store.laps(game, track_key, car, limit=200) if x["started_at"] >= self._stint_t0 - 1]
            laps.sort(key=lambda x: x["started_at"])
            if not laps:
                return
            reviews = {}
            for x in laps:
                rep = self.corner_report(x["id"], None, game=game, car=car, track_key=track_key)
                reviews[x["id"]] = rep.get("review") or {}
            best = self.store.best_lap(game, track_key, car)
            f = self.frame
            race = {"position": f.position} if f is not None and self.session is not None \
                and self.session.session_type.value == "race" and f.position else None
            with self.lock:
                focus = (self._coach_live() or {}).get("focus")
                self.pit_report = stint_report(laps, reviews, best["lap_time_ms"] if best else None,
                                               self._stint_cond, end, focus, race, laps_driven=driven)
                self.emit({"type": "pit_report", "report": self.pit_report})
            self.on_pit(game, car, track_key)
        except Exception:
            log.exception("Couldn't build the pit report")
