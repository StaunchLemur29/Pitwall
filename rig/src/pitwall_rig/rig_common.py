"""Shared by the rig and its parts: the analysis context, constants and small helpers."""


from __future__ import annotations

import logging
from typing import Any

from .analysis import (
    LapView,
)
from .tracks.live import TrackState

log = logging.getLogger(__name__)

Event = dict[str, Any]


class AnalysisCtx:
    """Everything the analysis needs for one car on one track: the live session,
    or any car + track you've driven before."""

    def __init__(self, game: str, car: str, track_key: str, track: TrackState, ref_lap_id: int | None, live: bool):
        self.game, self.car, self.track_key = game, car, track_key
        self.track = track
        self.ref_lap_id = ref_lap_id
        self.live = live
        self.lap_count = -1  # cache check for past combos


OPT_LAPS = 8


OPTIMAL = -1  # compare_id meaning "the optimal run" (the benchmark when there's no faster lap of yours)


TTB_LAPS = 10  # the time to beat starts from your usual over this many recent clean laps


TTB_PAST_BEST = 0.003  # the lap's time to beat asks at most 0.3 % beyond your best lap


OPT_KEYS = ("time_s", "brake_m", "entry_kmh", "peak_brake", "min_speed_kmh", "throttle_m", "exit_kmh")


def _locked(fn):  # type: ignore[no-untyped-def]
    """Rig state is touched by the telemetry thread and the web server: one at a time."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):  # type: ignore[no-untyped-def]
        with self.lock:
            return fn(self, *a, **kw)

    return wrapper


def _summary_targets(rep: dict[str, Any], model_corners: dict[int, Any]) -> dict[str, Any] | None:
    """The time to beat, condensed for the debrief: the lap, the corners with
    the most to gain, and the practice sections."""
    tb = rep.get("time_to_beat")
    if not tb:
        return None
    top = sorted(tb["corners"], key=lambda c: -c["gain_s"])[:4]
    return {
        "lap": fmt_ms(tb["lap_ms"]),
        "usual_lap": fmt_ms(tb["usual_lap_ms"]),
        "corners": [{"corner": model_corners[c["corner"]].label if c["corner"] in model_corners else f"Corner {c['corner']}",
                     "to_beat_s": c["target_s"], "usual_s": c["usual_s"], "why": c["why"]} for c in top],
        "practice_sections": [{"name": ps["name"], "to_beat_s": ps.get("to_beat_s")}
                              for ps in rep.get("practice", []) if ps.get("to_beat_s")],
    }


def _covers(view: LapView, a: float, b: float) -> bool:
    """The lap's telemetry runs from ``a`` to ``b`` (an unfinished lap may stop short)."""
    return bool(view.p) and view.p[0] <= a + 0.002 and view.p[-1] >= b - 0.002


def fmt_ms(ms: int) -> str:
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"
