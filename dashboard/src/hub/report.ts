/**
 * The hub's lap breakdown: the same report the rig PC builds (rig/src/pitwall_rig
 * rig.py corner_report + analysis.py compare_notes / corner_mastery), worked out
 * in the browser from uploaded laps. The PC uploads each lap's own analysis
 * (corner numbers, track-width advice, battery & DRS); comparing laps happens
 * here, so you can compare against any lap. Keep in step with the Python; the
 * test checks both give the same answers on the same laps.
 */
import { timeLookup, type Trace } from "../lib/profile";
import type { CarProfile, CornerLap, CornerReport, LapReview, Mastery, TimeToBeat, TrackGeometry } from "../lib/types";

/** A lap as uploaded (the columns the report needs). */
export interface HubLap {
  id: number;
  lap_number: number;
  lap_time_ms: number;
  valid: boolean;
  out_lap?: boolean;
  rewound?: boolean; // used a rewind: never a best lap
  unfinished?: boolean; // didn't get to the line: only some corners driven
  started_at: number; // unix seconds
  sector_ms: number[];
  corners: CornerLap[] | null;
  systems: CornerReport["systems"];
  time_to_beat?: TimeToBeat | null; // the PC's targets as they stood after this lap
  review?: LapReview | null; // the PC's review of this lap, uploaded with it
  sections?: [number, number, number][] | null; // its clean passes through the practice sections: [start, end, ms]
}

const r3 = (x: number) => Math.round(x * 1000) / 1000;

/** Python's f"{x:.Nf}" (round half to even), so the notes read identically. */
function fmt(x: number, digits: number): string {
  const k = 10 ** digits;
  const v = x * k;
  const f = Math.floor(v);
  const diff = v - f;
  const n = Math.abs(diff - 0.5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(v);
  return (n / k).toFixed(digits);
}

export function compareNotes(mine: CornerLap, other: CornerLap, label: string): string[] {
  const notes: [number, string][] = [];
  const dv = mine.min_speed_kmh - other.min_speed_kmh;
  if (Math.abs(dv) >= 3) {
    notes.push([Math.abs(dv) * 1.5, `${fmt(Math.abs(dv), 0)} km/h ${dv < 0 ? "slower" : "faster"} at the slowest point than ${label}.`]);
  }
  if (mine.exit_kmh != null && other.exit_kmh != null) {
    const de = mine.exit_kmh - other.exit_kmh;
    if (Math.abs(de) >= 3) {
      notes.push([Math.abs(de) * 1.2, `${fmt(Math.abs(de), 0)} km/h ${de < 0 ? "slower" : "faster"} on the exit than ${label}.`]);
    }
  }
  const mb = mine.brake_m ?? null;
  const ob = other.brake_m ?? null;
  if (mb !== null && ob !== null && Math.abs(mb - ob) >= 8) {
    const d = mb - ob;
    notes.push([Math.abs(d) / 3, `Braked ${Math.abs(d)} m ${d > 0 ? "earlier" : "later"} than ${label}.`]);
  } else if (mb !== null && ob === null) {
    notes.push([5, `You braked here; ${label} didn't.`]);
  } else if (mb === null && ob !== null) {
    notes.push([5, `You didn't brake here; ${label} did.`]);
  }
  const mt = mine.throttle_m ?? null;
  const ot = other.throttle_m ?? null;
  if (mt !== null && ot !== null && Math.abs(mt - ot) >= 10) {
    const d = mt - ot;
    notes.push([Math.abs(d) / 4, `Back to full throttle ${Math.abs(d)} m ${d > 0 ? "later" : "earlier"} than ${label}.`]);
  }
  const dc = (mine.coast_s ?? 0) - (other.coast_s ?? 0);
  if (dc >= 0.3) notes.push([dc * 10, `Coasted ${fmt(dc, 1)} s longer than ${label} (no brake, no throttle).`]);
  if (mine.apex_gear && other.apex_gear && mine.apex_gear !== other.apex_gear) {
    notes.push([2, `Gear ${mine.apex_gear} at the apex; ${label} used ${other.apex_gear}.`]);
  }
  return notes.sort((a, b) => b[0] - a[0]).map(([, t]) => t);
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function pstdev(xs: number[]): number {
  const mu = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, b) => a + (b - mu) ** 2, 0) / xs.length);
}

/** Per corner: best and recent times, consistency, green / amber / red. ``history`` newest first. */
/** Whether a corner of a lap counts towards your usual and bests (analysis.py counts). */
export function counts(c: CornerLap, lapValid: boolean): boolean {
  if (c.driven === false) return false;
  return c.clean ?? lapValid;
}
export const OPTIMAL = -1; // compare_id: the optimal run (rig.py OPTIMAL)

export function cornerMastery(history: CornerLap[][], recent = 10): Map<number, Mastery> {
  const byCorner = new Map<number, number[]>();
  for (const lap of history) for (const c of lap) byCorner.set(c.corner, [...(byCorner.get(c.corner) ?? []), c.time_s]);
  const out = new Map<number, Mastery>();
  for (const [num, times] of byCorner) {
    const last = times.slice(0, recent);
    const best = Math.min(...times);
    const spread = last.length > 1 ? pstdev(last) : null;
    const gap = median(last) - best;
    const grade: Mastery["grade"] =
      last.length < 3 ? "new"
      : spread !== null && spread <= 0.08 && gap <= 0.12 ? "green"
      : spread !== null && spread <= 0.2 && gap <= 0.3 ? "amber"
      : "red";
    out.set(num, { corner: num, best_s: r3(best), median_s: r3(median(last)), spread_s: spread !== null ? r3(spread) : null, laps: times.length, grade });
  }
  return out;
}

/** Which systems a car has, as a short list (same as car_profile.summary). */
export function carSummary(p: CarProfile | null): string[] {
  if (!p) return [];
  const out: string[] = [];
  if (p.abs) out.push(p.abs_levels ? `ABS (${p.abs_levels})` : "ABS");
  if (p.tc) out.push(p.tc_levels ? `TC (${p.tc_levels})` : "TC");
  if (p.brake_bias) out.push("Brake bias");
  // Only what's been seen working: some mod cars claim systems they don't have.
  if (p.drs && p.drs_seen) out.push("DRS");
  if (p.battery && p.battery_seen) out.push(p.ers ? (p.deploy_modes ? `ERS (${p.deploy_modes} deploy modes)` : "ERS") : "KERS");
  if (p.engine_brake_maps) out.push(`Engine braking (${p.engine_brake_maps} maps)`);
  return out;
}

export interface ReportInput {
  game: string;
  car: string;
  track_key: string;
  laps: HubLap[]; // every lap of this car + track
  geometry: TrackGeometry;
  profile: CarProfile | null;
  /** Telemetry of the shown lap and of the best lap (for section and chapter times). */
  traces: Map<number, Trace>;
}

export function buildReport(inp: ReportInput, lapId: number | null, compareId: number | null): CornerReport {
  const valid = inp.laps.filter((l) => l.valid).sort((a, b) => b.started_at - a.started_at);
  const byId = new Map(inp.laps.map((l) => [l.id, l]));
  const best = valid.filter((l) => !l.rewound).sort((a, b) => a.lap_time_ms - b.lap_time_ms || a.id - b.id)[0] ?? null;
  const refId = best?.id ?? null;
  const shownId = lapId ?? valid[0]?.id ?? null;
  const shown = shownId !== null ? byId.get(shownId) ?? null : null;

  // Your recent driving through each corner (rig.py _history): the corners that
  // count (driven all the way, clean) from any lap, finished or not, newest first.
  const history: CornerLap[][] = [];
  for (const l of [...inp.laps].sort((a, b) => b.started_at - a.started_at).slice(0, 90)) {
    const good = (l.corners ?? []).filter((c) => counts(c, l.valid));
    if (good.length) history.push(good);
    if (history.length >= 30) break;
  }
  const mastery = cornerMastery(history);
  const lap = shown?.corners ? shown.corners.map((c) => ({ ...c })) : null;
  if (lap) {
    for (const c of lap) {
      if (c.driven === false) continue; // not driven on this lap: nothing to compare
      const b = mastery.get(c.corner)?.best_s;
      c.loss_s = b !== undefined ? r3(c.time_s - b) : null;
    }
  }

  // Coaching, not lap comparison (rig.py): only ever against something faster.
  // Your best lap if it's quicker than this one; on your best (or a lap quicker
  // only by cutting), the benchmark: the optimal run (OPTIMAL = -1).
  let cmp: HubLap | null = null;
  let kind: CornerReport["compare_kind"] = null;
  let optLabel: string | null = null;
  let optCompare: CornerLap[] | null = null;
  if (lap && shownId !== null) {
    if (compareId === null) {
      const fullLap = !!shown && !shown.out_lap && !shown.unfinished;
      compareId = best && best.id !== shownId && (!fullLap || best.lap_time_ms < shown!.lap_time_ms) ? best.id : OPTIMAL;
    }
    if (compareId === OPTIMAL) {
      const rows = lap.filter((c) => c.opt);
      if (rows.length) {
        kind = "optimal";
        optLabel = "the optimal run";
        optCompare = rows.map((c) => ({ ...(c.opt as unknown as CornerLap), corner: c.corner }));
        for (const c of lap) {
          if (!c.opt || c.driven === false) continue;
          c.vs_s = r3(c.time_s - c.opt.time_s);
          c.notes = c.opt_notes?.length ? c.opt_notes : compareNotes(c, c.opt as unknown as CornerLap, optLabel).slice(0, 3);
        }
      }
    } else {
      cmp = compareId !== null && compareId !== shownId ? byId.get(compareId) ?? null : null;
      if (cmp) kind = "lap";
    }
  }
  const label = cmp ? (cmp.id === refId ? "your best lap" : `lap ${cmp.lap_number}`) : optLabel;
  if (lap && cmp?.corners && label) {
    const other = new Map(cmp.corners.map((c) => [c.corner, c]));
    for (const c of lap) {
      const o = other.get(c.corner);
      if (o && c.driven !== false && o.driven !== false) {
        c.vs_s = r3(c.time_s - o.time_s);
        c.notes = compareNotes(c, o, label);
      }
    }
  }

  const span = (tr: Trace | undefined, a: number, b: number) => {
    if (!tr || b <= a || !tr.p.length) return null;
    // an unfinished lap may stop short (rig.py _covers)
    if (Math.min(...tr.p) > a + 0.002 || Math.max(...tr.p) < b - 0.002) return null;
    const at = timeLookup(tr);
    return r3(at(b) - at(a));
  };
  const shownTrace = shownId !== null ? inp.traces.get(shownId) : undefined;
  const refTrace = refId !== null ? inp.traces.get(refId) : undefined;
  // Time to beat: the PC works it out; the newest lap carries the latest.
  const newest = [...inp.laps].filter((l) => l.time_to_beat).sort((a, b) => b.started_at - a.started_at)[0];
  const tbAll = newest?.time_to_beat ?? null;
  const tb = tbAll ? { lap_ms: tbAll.lap_ms, usual_lap_ms: tbAll.usual_lap_ms, corners: tbAll.corners } : null;
  if (lap && tb) {
    const targets = new Map(tb.corners.map((c) => [c.corner, c.target_s]));
    for (const c of lap) c.to_beat_s = targets.get(c.corner) ?? null;
  }
  const sectionTargets = new Map((tbAll?.sections ?? []).map((s) => [s.number, s.to_beat_s]));
  // Your best through each section from any lap (rig.py _record_sections; the
  // PC also counts drill runs, which aren't uploaded).
  const sectionBest = (a: number, b: number): number | null => {
    let best: number | null = null;
    for (const l of inp.laps)
      for (const [s, e, ms] of l.sections ?? [])
        if (Math.abs(s - a) < 1e-4 && Math.abs(e - b) < 1e-4 && (best === null || ms < best)) best = ms;
    return best !== null ? best / 1000 : null;
  };
  const practice = inp.geometry.practice.map((ps) => ({
    ...ps,
    time_s: span(shownTrace, ps.start, ps.end),
    ref_s: span(refTrace, ps.start, ps.end),
    drill_best_s: sectionBest(ps.start, ps.end),
    to_beat_s: sectionTargets.get(ps.number) ?? null,
  }));
  const chapters = inp.geometry.chapters.map((ch) => ({
    ...ch,
    time_s: span(shownTrace, ch.start, ch.end),
    ref_s: span(refTrace, ch.start, ch.end),
  }));

  // Best sectors combined.
  let sectors: number[] = [];
  for (const l of valid) {
    if (l.rewound) continue;
    if (!sectors.length) sectors = [...l.sector_ms];
    else if (l.sector_ms.length === sectors.length) sectors = sectors.map((s, i) => Math.min(s, l.sector_ms[i]));
  }

  return {
    game: inp.game,
    car: inp.car,
    track_key: inp.track_key,
    live: false,
    theoretical_best_ms: sectors.length ? sectors.reduce((a, b) => a + b, 0) : null,
    time_to_beat: tb,
    systems: shown?.systems ?? null,
    review: shown?.review ?? null,
    car_systems: carSummary(inp.profile),
    compare: cmp?.corners ?? optCompare,
    compare_lap_id: cmp ? cmp.id : null,
    compare_label: label,
    compare_kind: kind,
    chapters,
    practice,
    mastery: [...mastery.values()],
    lap_id: shownId,
    lap,
    reference: best?.corners ?? [],
    reference_lap_id: refId,
  };
}
