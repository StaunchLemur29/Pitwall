"""The side screen's coach strip: the focus corner, each lap's biggest mistake, cold tyres, live tips, and the time to beat.

A part of the Rig (rig.py): its methods use the Rig's state."""

from __future__ import annotations

import logging
import statistics
import time
from typing import Any

from .analysis import (
    LapView,
    time_to_beat,
)
from .models import Frame, GameStatus, Lap
from .rig_common import (
    TTB_LAPS,
    TTB_PAST_BEST,
    AnalysisCtx,
)
from .tips import SHOW_UNTIL_M, as_instruction

log = logging.getLogger(__name__)


class CoachMixin:
    COLD_MARGIN_C = 12.0  # this far under the usual working temperature counts as cold

    COLD_DEFAULT_C = 55.0  # until Pitwall has seen this car's tyres working

    def _coach_after_lap(self, lap_id: int, rep: dict[str, Any], tb: dict[str, Any] | None) -> None:
        """After a lap: its biggest mistake for the strip, and keep (or move on
        from) the session's focus corner."""
        info = self.store.lap(lap_id)
        review = rep.get("review") or {}
        wrong = (review.get("wrong") or [None])[0]
        self._last_lap_note = {"lap": info["lap_number"] if info else None, "at": time.time(),
                               "wrong": {"label": wrong["label"], "text": wrong["text"], "lost_s": wrong.get("lost_s")}
                               if wrong else None}
        rows = {c["corner"]: c for c in rep.get("lap") or []}
        self._last_rows = rows
        self.tips.add_lap(review.get("wrong") or [])
        targets = {c["corner"]: c for c in (tb or {}).get("corners", [])}
        f = self._focus
        if f is not None and f["corner"] in rows and f["corner"] in targets:
            mine = rows[f["corner"]]
            if mine.get("driven") is not False and mine["time_s"] <= targets[f["corner"]]["target_s"]:
                f["beaten"] += 1
            if f["beaten"] >= 2:  # met twice: on to the next one
                self._focus_met.add(f["corner"])
                self._focus = f = None
        if f is None:
            self._pick_focus(tb)

    def _pick_focus(self, tb: dict[str, Any] | None) -> None:
        """The one corner to work on this session: the most time to gain against
        its time to beat (one you haven't already met this session)."""
        options = [c for c in (tb or {}).get("corners", []) if c["gain_s"] >= 0.05 and c["corner"] not in self._focus_met]
        if options:
            self._focus = {"corner": max(options, key=lambda c: c["gain_s"])["corner"], "beaten": 0}

    def _coach_live(self) -> dict[str, Any] | None:
        """What the side screen's coach strip shows (cheap: sent with every frame)."""
        if self.track is None:
            return None
        out: dict[str, Any] = {"focus": None, "last_lap": None, "tyres": None}
        f = self._focus
        tb = self._ttb.get((self.session.game, self.session.car, self.session.track_key), {}).get("tb") if self.session else None
        if f is not None and tb:
            t = next((c for c in tb["corners"] if c["corner"] == f["corner"]), None)
            c = next((c for c in self.track.model.corners if c.number == f["corner"]), None)
            if t and c:
                ps = next((p for p in self.track.model.practice if f["corner"] in p.corners), None)
                out["focus"] = {
                    "corner": c.number, "label": c.label, "to_beat_s": t["target_s"], "usual_s": t["usual_s"],
                    "gain_s": t["gain_s"], "why": t["why"], "fix": self._focus_fix(c.number), "beaten": f["beaten"],
                    "section": {"number": ps.number, "name": ps.name} if ps else None,
                }
        n = self._last_lap_note
        if n and time.time() - n["at"] < 25:
            out["last_lap"] = {k: v for k, v in n.items() if k != "at"}
        if self._tyres_cold:
            avg = self._tyre_avg()
            out["tyres"] = {"cold": True, "avg_c": round(avg) if avg else None, "working_c": round(self._working_c())}
        out["notice"] = self.conditions.current_notice(self._clock())  # a crash, worn tyres, the track changing...
        out["tip"] = self._tip_live(out)
        return out

    def _tip_live(self, coach: dict[str, Any]) -> dict[str, Any] | None:
        """This frame's live tip (see tips.py), or None."""
        f, track = self.frame, self.track
        if self.config["coach"].get("tips", "game") == "off" or f is None or track is None or f.status != GameStatus.LIVE:
            return None
        nc = track.model.next_corner(f.lap_progress)
        quiet = bool(track.drill is not None or coach.get("notice") or coach.get("tyres") or f.in_pit_lane)
        corners = track.model.corners
        length = track.model.length_m or 1.0

        def approach(num: int) -> int:
            # back over linked corners (less than a reading-straight between them) to the run's first
            i = next((k for k, c in enumerate(corners) if c.number == num), None)
            if i is None:
                return num
            for _ in range(min(2, len(corners) - 1)):  # at most two corners back, or it's not "before" it
                prev = corners[i - 1]
                if ((corners[i].entry - prev.exit) % 1.0) * length >= SHOW_UNTIL_M:
                    break
                i -= 1
            return corners[i].number

        tip = self.tips.live(f.lap, nc[0].number if nc else None, nc[1] if nc else None, self._clock(),
                             coach.get("focus"), quiet, approach)
        if tip and nc and tip["corner"] != nc[0].number:
            # given on the straight before a run of corners: say which one it's about
            tip = {**tip, "label": f"{tip['label']}, after {nc[0].label}"}
        return tip

    def _focus_fix(self, corner: int) -> str | None:
        """What to change at the focus corner, as something to do: from your
        latest lap there, the first difference that cost time (not one where you
        were quicker)."""
        last = self._last_rows.get(corner)
        if not last:
            return None
        notes = (last.get("notes") or []) + (last.get("opt_notes") or [])
        return next((x for x in (as_instruction(n) for n in notes) if x), None)

    def _tyre_avg(self) -> float | None:
        f = self.frame
        temps = f.tyre_core_temp_c if f else None
        return sum(temps) / len(temps) if temps else None

    def _working_c(self) -> float:
        p = self.car_profile or {}
        return float(p.get("tyre_working_c") or self.COLD_DEFAULT_C + self.COLD_MARGIN_C)

    def _note_tyres(self, frame: Frame) -> None:
        """Learn the temperature this car's tyres work at (on your laps, at speed),
        and whether they're cold now (until they're back near it)."""
        temps = frame.tyre_core_temp_c
        if not temps or frame.status != GameStatus.LIVE:
            return
        avg = sum(temps) / len(temps)
        if frame.speed_kmh > 80:
            self._tyre_sum += avg
            self._tyre_n += 1
        working = self._working_c()
        if frame.in_pit_box or frame.speed_kmh < 5:
            self._tyres_cold = avg < working - self.COLD_MARGIN_C
        elif self._tyres_cold and avg >= working - self.COLD_MARGIN_C / 2:
            self._tyres_cold = False  # warmed up (with a margin so it doesn't flicker)
        elif not self._tyres_cold and avg < working - self.COLD_MARGIN_C * 1.5:
            self._tyres_cold = True  # e.g. after a reset or teleport

    def _learn_tyre_temp(self, lap: Lap) -> None:
        if self._tyre_n > 200 and lap.valid and self.car_profile is not None:
            lap_avg = self._tyre_sum / self._tyre_n
            old = self.car_profile.get("tyre_working_c")
            self.car_profile["tyre_working_c"] = round(lap_avg if old is None else 0.7 * old + 0.3 * lap_avg, 1)
            self._save_car_profile()
        self._tyre_sum, self._tyre_n = 0.0, 0

    def _time_to_beat(self, ctx: AnalysisCtx | None) -> dict[str, Any] | None:
        """A realistic stretch target for the lap and each corner (see
        analysis.time_to_beat): your usual lap, minus what each corner's target
        asks of you. None until there are 3 clean laps."""
        if ctx is None:
            return None
        key = (ctx.game, ctx.car, ctx.track_key)
        ids = self.store.valid_lap_ids(ctx.game, ctx.track_key, ctx.car, limit=TTB_LAPS)
        run = self._opt_runs.get(key)
        rows = run.get("rows") if run else None
        sig = (tuple(ids), id(rows), self._model_sig(ctx.track))
        known = self._ttb.get(key)
        if known is not None and known["sig"] == sig:
            return known["tb"]
        tb = None
        laps = [lap for lap in (self.store.lap(i) for i in ids) if lap and not lap.get("rewound")]
        if len(laps) >= 3:
            mastery = ctx.track.mastery or self._mastery(ctx)
            corners = time_to_beat(mastery, rows)
            usual = statistics.median(lap["lap_time_ms"] for lap in laps)
            gain_ms = sum(c["gain_s"] for c in corners.values()) * 1000
            # Every corner at its stretch at once adds up to more than one lap
            # realistically gives: never ask for much more than your best lap.
            best = self.store.best_lap(ctx.game, ctx.track_key, ctx.car)
            floor = best["lap_time_ms"] * (1 - TTB_PAST_BEST) if best else 0
            tb = {"lap_ms": round(min(usual, max(usual - gain_ms, floor))), "usual_lap_ms": round(usual),
                  "corners": sorted(corners.values(), key=lambda c: c["corner"])}
        self._ttb[key] = {"sig": sig, "tb": tb, "ids": ids, "views": None}
        return tb

    def _span_to_beat(self, ctx: AnalysisCtx | None, start_p: float, end_p: float,
                      tb: dict[str, Any] | None | bool = True) -> dict[str, float] | None:
        """Time to beat for a stretch of track (a drill, a practice section):
        your usual time through it over recent clean laps, minus what the
        corners in it ask of you. Seconds; None without enough laps."""
        if tb is True:  # not worked out by the caller (it passes it, or None, to save asking again)
            tb = self._time_to_beat(ctx)
        if tb is None or ctx is None or not end_p > start_p:
            return None
        known = self._ttb[(ctx.game, ctx.car, ctx.track_key)]
        if known["views"] is None:
            known["views"] = [LapView.of(t) for t in (self.store.trace(i) for i in known["ids"]) if t]
        spans = [v.time_at(end_p) - v.time_at(start_p) for v in known["views"] if v]
        spans = [s for s in spans if s > 0]
        if len(spans) < 3:
            return None
        usual = statistics.median(spans)
        corners = {c.number: c for c in ctx.track.model.corners}
        gain = sum(c["gain_s"] for c in tb["corners"]
                   if c["corner"] in corners and start_p <= corners[c["corner"]].apex <= end_p)
        return {"usual_s": round(usual, 3), "to_beat_s": round(usual - gain, 3)}
