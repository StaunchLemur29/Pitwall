/**
 * The session summary Claude reads for a debrief: the same shape the rig PC
 * sends (rig.py session_summary), built here from uploaded laps so the hub can
 * ask for a debrief while the PC is off. Keep in step with the Python; the
 * test checks both give the same summary for the same laps.
 */
import type { CornerReport, TrackGeometry } from "../lib/types";
import type { HubLap } from "./report";
import { SESSION_GAP_S } from "./sessions";

export const MIN_CLEAN_LAPS = 3; // same as debrief.py

/** Python's fmt_ms: 0:57.441 */
export function fmtMs(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = (ms - m * 60000) / 1000;
  return `${m}:${s.toFixed(3).padStart(6, "0")}`;
}

/** The latest session's laps (oldest first), or null when there are no laps. */
export function latestSession(laps: HubLap[]): HubLap[] | null {
  const sorted = [...laps].sort((a, b) => a.started_at - b.started_at);
  let sess: HubLap[] = [];
  for (const l of sorted) {
    if (sess.length && l.started_at - sess[sess.length - 1].started_at <= SESSION_GAP_S) sess.push(l);
    else sess = [l];
  }
  return sess.length ? sess : null;
}

/** The fastest lap of these, leaving out laps with a rewind in them unless that's all there is. */
function bestOf(clean: HubLap[]): HubLap {
  const pool = clean.filter((l) => !l.rewound);
  return (pool.length ? pool : clean).reduce((a, b) => (b.lap_time_ms < a.lap_time_ms ? b : a));
}

/** The session's best clean lap, if the session has enough clean laps for a debrief. */
export function debriefLap(laps: HubLap[]): HubLap | null {
  const sess = latestSession(laps);
  const clean = (sess ?? []).filter((l) => l.valid);
  if (clean.length < MIN_CLEAN_LAPS) return null;
  return bestOf(clean);
}

/** ``rep`` is the report of the session's best lap (debriefLap) with its default comparison. */
export function sessionSummary(
  car: string,
  trackKey: string,
  laps: HubLap[],
  rep: CornerReport,
  geometry: TrackGeometry | null,
): Record<string, unknown> | null {
  const sess = latestSession(laps);
  if (!sess) return null;
  const clean = sess.filter((l) => l.valid);
  if (clean.length < MIN_CLEAN_LAPS) return null;
  const start = sess[0].started_at;
  const best = bestOf(clean);
  const before = laps.filter((l) => l.valid && !l.rewound && l.started_at < start).map((l) => l.lap_time_ms);
  const times = clean.map((l) => l.lap_time_ms).sort((a, b) => a - b);
  const mid = times.length >> 1;
  const median = times.length % 2 ? times[mid] : (times[mid - 1] + times[mid]) / 2;
  const mean = times.reduce((a, b) => a + b, 0) / times.length;
  const spread = Math.sqrt(times.reduce((a, t) => a + (t - mean) ** 2, 0) / times.length);

  const modelCorners = new Map((geometry?.corners ?? []).map((c) => [c.number, c]));
  const mastery = new Map(rep.mastery.map((m) => [m.corner, m]));
  const corners = (rep.lap ?? []).map((c) => {
    const mc = modelCorners.get(c.corner);
    const m = mastery.get(c.corner);
    return {
      corner: mc ? mc.label : `Corner ${c.corner}`,
      type: mc ? `${mc.direction}${mc.grade} (1 = tightest, 6 = flat)` : null,
      time_s: c.time_s,
      vs_comparison_s: c.vs_s ?? null,
      differences: (c.notes ?? []).slice(0, 3),
      lost_vs_best_ever_here_s: c.loss_s ?? null,
      consistency: { grade: m?.grade ?? null, spread_s: m?.spread_s ?? null, laps: m?.laps ?? null },
      track_width_advice: (c.advice ?? []).slice(0, 1),
      slowest_kmh: c.min_speed_kmh ?? null,
      gear: c.apex_gear ?? null,
      brake_m_before_apex: c.brake_m ?? null,
    };
  });
  const pbBefore = before.length ? Math.min(...before) : null;
  return {
    car,
    track: trackKey,
    session: {
      start,
      laps: sess.map((l) => ({ lap: l.lap_number, time: fmtMs(l.lap_time_ms), clean: l.valid, out_lap: l.out_lap ?? false, rewound: !!l.rewound })),
      clean_laps: clean.length,
      best: fmtMs(best.lap_time_ms),
      typical: fmtMs(Math.trunc(median)),
      spread_s: Math.round(spread / 10) / 100,
    },
    personal_best_before_session: pbBefore !== null ? fmtMs(pbBefore) : null,
    new_personal_best: pbBefore === null || best.lap_time_ms < pbBefore,
    best_sectors_combined: rep.theoretical_best_ms ? fmtMs(rep.theoretical_best_ms) : null,
    best_lap_compared_with: rep.compare_label ?? null,
    conditions_on_best_lap: rep.conditions ?? null,
    corners_on_best_lap: corners,
    practice_sections: rep.practice.map((ps) => ({
      name: ps.name, this_lap_s: ps.time_s ?? null, best_lap_s: ps.ref_s ?? null, best_drill_run_s: ps.drill_best_s ?? null,
    })),
    battery_and_drs: rep.systems?.notes ?? [],
    car_has: rep.car_systems ?? [],
    time_to_beat: summaryTargets(rep, modelCorners),
  };
}

/** The time to beat, condensed for the debrief (rig.py _summary_targets). */
function summaryTargets(rep: CornerReport, modelCorners: Map<number, { label: string }>): Record<string, unknown> | null {
  const tb = rep.time_to_beat;
  if (!tb) return null;
  const top = [...tb.corners].sort((a, b) => b.gain_s - a.gain_s).slice(0, 4);
  return {
    lap: fmtMs(tb.lap_ms),
    usual_lap: fmtMs(tb.usual_lap_ms),
    corners: top.map((c) => ({
      corner: modelCorners.get(c.corner)?.label ?? `Corner ${c.corner}`,
      to_beat_s: c.target_s,
      usual_s: c.usual_s,
      why: c.why,
    })),
    practice_sections: rep.practice.filter((ps) => ps.to_beat_s).map((ps) => ({ name: ps.name, to_beat_s: ps.to_beat_s })),
  };
}
