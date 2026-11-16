"""Drills and the in-game CSP app: starting and stopping drills, retries (saved state or Time Shift), Go there, and the app's sync.

A part of the Rig (rig.py): its methods use the Rig's state."""

from __future__ import annotations

import logging
from typing import Any

from . import car_profile
from .models import Frame, GameStatus
from .rig_common import (
    _locked,
)
from .tracks.live import Drill

log = logging.getLogger(__name__)


class DrillsMixin:
    @_locked
    def drill_section(self, number: int) -> bool:
        if self.track is None:
            return False
        ps = next((p for p in self.track.model.practice if p.number == number), None)
        return ps is not None and self.start_drill(ps.start, ps.end, ps.name)

    @_locked
    def drill_chapter(self, number: int) -> bool:
        if self.track is None:
            return False
        ch = next((c for c in self.track.model.chapters if c.number == number), None)
        return ch is not None and self.start_drill(ch.start, ch.end, ch.name)

    @_locked
    def start_drill(self, start_p: float, end_p: float, name: str, corner: int | None = None) -> bool:
        s = self.session
        if self.track is None or s is None:
            return False
        drill = Drill(name=name, start_p=start_p % 1.0, end_p=end_p % 1.0, corner=corner)
        best = self.store.best_section_ms(s.game, s.car, s.track_key, drill.start_p, drill.end_p)
        span = self._span_to_beat(self._live_ctx(), drill.start_p, drill.end_p)
        self.track.start_drill(drill, best, int(span["to_beat_s"] * 1000) if span else None)
        self.emit({"type": "drill", "drill": self.track.drill.to_wire() if self.track.drill else None})
        return True

    @_locked
    def drill_corner(self, number: int) -> bool:
        if self.track is None:
            return False
        m = self.track.model
        c = next((c for c in m.corners if c.number == number), None)
        if c is None:
            return False
        before, after = 150.0 / m.length_m, 60.0 / m.length_m
        return self.start_drill(c.entry - before, c.exit + after, c.label, c.number)

    RETRY_EXTRA_M = 600.0  # don't stop if somehow way further back than the target

    @_locked
    def start_retry(self) -> bool:
        if self.track is None or self.track.drill is None or self.frame is None:
            return False
        if self.csp.can_reset and self.csp.state.get("has_launch"):
            # The in-game app saved the car at the run-up point: it puts you
            # straight back there, at speed.
            self.csp.send({"cmd": "retry", "key": self._drill_key()})
            self._retry = {"t0": self._clock(), "csp": True}
            self.emit({"type": "retry", "state": "rewinding"})
            return True
        return self._retry_with_time_shift()

    def _retry_with_time_shift(self) -> bool:
        if self.track is None or self.track.drill is None or self.frame is None:
            return False
        if not self.keys.down(self.config["games"]["ac"]["rewind_key"]):
            return False
        lead_s = float(self.config["drills"]["lead_in_s"])
        target = self.track.lead_in_m(self.track.drill.drill, lead_s)
        self._retry = {"t0": self._clock(), "p0": self.frame.lap_progress, "moved": 0.0, "target_m": target}
        self.emit({"type": "retry", "state": "rewinding"})
        return True

    def _retry_step(self, f: Frame, now: float) -> None:
        r = self._retry
        assert r is not None and self.track is not None
        if r.get("csp"):
            if now - r["t0"] > 2.0:  # the app didn't answer: rewind with Time Shift instead
                self._retry = None
                self._retry_with_time_shift()
            return
        drill = self.track.drill
        length = self.track.model.length_m
        done = None
        if drill is None:
            done = "stopped"
        else:
            behind_m = ((drill.drill.start_p - f.lap_progress) % 1.0) * length
            back_m = ((r["p0"] - f.lap_progress) % 1.0) * length
            if back_m < length / 2:
                r["moved"] = max(r["moved"], back_m)
            if r["target_m"] <= behind_m <= r["target_m"] + self.RETRY_EXTRA_M and r["moved"] > 1:
                done = "ready"
            elif now - r["t0"] > 1.5 and r["moved"] < 1:
                done = "no_rewind"  # Time Shift didn't react: key not bound?
            elif now - r["t0"] > 20:
                done = "timeout"
        if done:
            self.keys.up()
            self._retry = None
            self.emit({"type": "retry", "state": done})

    TELEPORT_EXTRA_M = 50.0  # always park a bit before the Time Shift run-up

    @_locked
    def teleport_to_drill(self) -> bool:
        """Park the car, stopped, far enough before the drill that pulling away
        flat out gets you to the section at your usual speed. Only to get there:
        retries rewind as normal."""
        if self.track is None or self.track.drill is None or not self.csp.can_reset:
            return False
        d = self.track.drill.drill
        run_up = self.track.lead_in_m(d, float(self.config["drills"]["lead_in_s"]))
        back = self.track.standing_start_m(d, min_m=run_up + self.TELEPORT_EXTRA_M, run_up_m=run_up)
        p = (d.start_p - back / self.track.model.length_m) % 1.0
        # Warm the tyres to what this car runs at on your laps (the reset leaves
        # them cold, and before a teleport they may be cold too, e.g. after the pits).
        tyre_c = (self.car_profile or {}).get("tyre_working_c")
        # At speed if the app has a car state saved before the run-up (warm tyres,
        # your normal speed, from an earlier pass); else parked here, stopped.
        run_up_p = (d.start_p - run_up / self.track.model.length_m) % 1.0
        self.csp.send({"cmd": "teleport", "key": self._drill_key(), "p": p, "tyre_c": tyre_c, "run_up_p": run_up_p})
        self.emit({"type": "retry", "state": "teleporting"})
        return True

    def _csp_save_ok(self) -> bool:
        """Whether the car is fit to save as a "Go there" start: on track at speed,
        tyres warm, no damage, not off or dirty, not mid-retry."""
        f = self.frame
        if f is None or f.status != GameStatus.LIVE or f.in_pit_lane or f.in_pit_box or f.speed_kmh < 40:
            return False
        if self._tyres_cold or self._retry is not None or f.tyres_out > 2:
            return False
        if f.damage and f.damage[-1] >= 0.5:
            return False
        return not (f.tyre_dirt and max(f.tyre_dirt) > 0.5)

    def _drill_key(self) -> str | None:
        d = self.track.drill.drill if self.track and self.track.drill else None
        return f"{d.start_p:.5f}-{d.end_p:.5f}" if d else None

    def _csp_drill(self) -> dict[str, Any] | None:
        if self.track is None or self.track.drill is None:
            return None
        d = self.track.drill.drill
        lead = self.track.lead_in_m(d, float(self.config["drills"]["lead_in_s"]))
        st = self.track.drill
        # The in-game timer's target: the time to beat while it's quicker than
        # your best run, else your best (same as the side screen).
        target = st.target_ms if st.target_ms and (not st.best_ms or st.target_ms < st.best_ms) else st.best_ms
        run_up_p = (d.start_p - lead / self.track.model.length_m) % 1.0
        return {
            "key": self._drill_key(),
            "name": d.name,
            "start_p": d.start_p,
            "end_p": d.end_p,
            "run_up_p": run_up_p,
            # retries start from the state saved here: only save it at your usual speed
            "run_up_kmh": self.track.ref_kmh_at(run_up_p),
            "target_ms": target,
            "target_is_best": target is not None and target == st.best_ms,
        }

    @_locked
    def csp_sync(self, body: dict[str, Any]) -> dict[str, Any]:
        """The in-game app checking in (about 10 times a second)."""
        was = self.csp.connected
        self.conditions.set_env(body.get("env") if isinstance(body.get("env"), dict) else None)
        for e in self.csp.sync(body):
            if e.get("type") == "teleport":
                state = "teleported_at_speed" if e.get("ok") and e.get("at_speed") else "teleported" if e.get("ok") else "no_teleport"
                self.emit({"type": "retry", "state": state})
            if e.get("type") == "tyres":  # two seconds after a teleport: did the tyres really warm up?
                log.info("Teleport tyres: %s (wanted %s, now %s)", e.get("result"), e.get("target_c"), e.get("now_c"))
                if e.get("result") != "warm":
                    self.emit({"type": "retry", "state": "teleported_cold"})  # this CSP couldn't warm them
            if e.get("type") == "retry" and self._retry is not None and self._retry.get("csp"):
                self._retry = None
                if e.get("ok"):
                    self.emit({"type": "retry", "state": "ready"})
                else:
                    self._retry_with_time_shift()  # e.g. no saved state yet
        if not was:
            self.emit({"type": "csp", "connected": True})
        if self.car_profile is not None and car_profile.note_csp(self.car_profile, self.csp.state):
            self._save_car_profile()
        return {
            "track_version": self.csp.version if self.track is not None else -1,
            "drill": self._csp_drill(),
            # the live tip, for the in-game overlay too (Settings: on the side screen and in the game)
            "tip": (self.tips.showing or {}).get("text") if self.config["coach"].get("tips", "game") == "game" else None,
            # the app saves car states as you drive (for "Go there" at speed) only when the car's fit
            "save_states": self._csp_save_ok(),
            "session": f"{self.session.car}@{self.session.track_key}" if self.session else None,
            "overlay": self.config["overlay"],  # set in Pitwall's Settings
            "commands": self.csp.take_commands(),
        }

    @_locked
    def csp_track(self) -> dict[str, Any] | None:
        """What the app needs to work out the next corner and brake point by itself."""
        if self.track is None:
            return None
        m = self.track.model
        ref = self.track.ref_corners
        cue_corners, v = self.track.cue()  # the optimal run, or your best lap
        corners = []
        for c in m.corners:
            r, t = ref.get(c.number, {}), cue_corners.get(c.number, {})
            corners.append({
                "n": c.number, "label": c.label, "dir": c.direction, "grade": c.grade,
                "entry": c.entry, "apex": c.apex, "exit": c.exit,
                "brake_p": t.get("brake_p"), "entry_kmh": t.get("entry_kmh"),
                "min_kmh": t.get("min_speed_kmh"), "min_p": t.get("min_speed_p"),
                "gear": r.get("apex_gear") or t.get("apex_gear") or None,
            })
        # The target's speed every 1/1000th of the lap, for the speed-adjusted brake point.
        speed = [round(v.trace["speed"][v.at(i / 1000)], 1) for i in range(1000)] if v else []
        return {"version": self.csp.version, "length_m": m.length_m, "corners": corners, "ref_speed": speed}

    @_locked
    def stop_drill(self) -> None:
        if self.track is not None:
            self.track.stop_drill()
        self.emit({"type": "drill", "drill": None})

    def _save_attempt(self, a: dict[str, Any]) -> None:
        s = self.session
        if s is not None:
            self.store.add_section_attempt(
                s.game, s.car, s.track_key, a["start_p"], a["end_p"], a["time_ms"], a["clean"]
            )
