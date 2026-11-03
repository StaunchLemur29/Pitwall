/** The hub's data: your uploaded laps in Supabase, read-only, compared in the browser. */
import type { SupabaseClient } from "@supabase/supabase-js";
import type { Trace } from "../lib/profile";
import type { Combo } from "../lib/rig";
import type { AnalysisSource } from "../lib/source";
import type { CarProfile, CornerReport, LapSummary, TrackGeometry } from "../lib/types";
import { buildReport, type HubLap } from "./report";

const key = (c: { game: string; car: string; track_key: string }) => `${c.game}|${c.car}|${c.track_key}`;
const unix = (iso: string) => Date.parse(iso) / 1000;

/** All rows of a query, a page at a time (Supabase returns at most 1000 per request). */
async function all<T>(page: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: unknown }>): Promise<T[]> {
  const out: T[] = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await page(from, from + 999);
    if (error) throw error;
    out.push(...(data ?? []));
    if (!data || data.length < 1000) return out;
  }
}

interface LapRow {
  id: number;
  game: string;
  car: string;
  track_key: string;
  lap_number: number;
  lap_time_ms: number;
  valid: boolean;
  out_lap: boolean;
  started_at: string;
  sector_ms: number[];
  corners?: HubLap["corners"];
  systems?: HubLap["systems"];
}

export function hubSource(sb: SupabaseClient): AnalysisSource {
  const lapsByCombo = new Map<string, Promise<LapRow[]>>();
  const geometry = new Map<string, Promise<TrackGeometry | null>>();
  const profiles = new Map<string, Promise<CarProfile | null>>();
  const traces = new Map<number, Promise<Trace | null>>();

  const comboLaps = (c: Combo) => {
    const k = key(c);
    if (!lapsByCombo.has(k)) {
      lapsByCombo.set(k, all<LapRow>((a, b) =>
        sb.from("laps")
          .select("id,game,car,track_key,lap_number,lap_time_ms,valid,out_lap,started_at,sector_ms,corners,systems")
          .eq("game", c.game).eq("car", c.car).eq("track_key", c.track_key)
          .order("started_at", { ascending: false }).range(a, b)));
    }
    return lapsByCombo.get(k)!;
  };
  const trackGeometry = (c: Combo) => {
    const k = `${c.game}|${c.track_key}`;
    if (!geometry.has(k)) {
      geometry.set(k, Promise.resolve(sb.from("tracks").select("geometry").eq("game", c.game).eq("track_key", c.track_key).maybeSingle())
        .then(({ data }) => (data?.geometry as TrackGeometry) ?? null));
    }
    return geometry.get(k)!;
  };
  const carProfile = (c: Combo) => {
    const k = `${c.game}|${c.car}`;
    if (!profiles.has(k)) {
      profiles.set(k, Promise.resolve(sb.from("car_profiles").select("profile").eq("game", c.game).eq("car", c.car).maybeSingle())
        .then(({ data }) => (data?.profile as CarProfile) ?? null));
    }
    return profiles.get(k)!;
  };
  const trace = (id: number) => {
    if (!traces.has(id)) {
      traces.set(id, Promise.resolve(sb.from("laps").select("trace").eq("id", id).maybeSingle()).then(({ data }) => (data?.trace as Trace) ?? null));
    }
    return traces.get(id)!;
  };

  return {
    live: false,

    async combos() {
      const rows = await all<{ game: string; car: string; track_key: string; lap_time_ms: number; valid: boolean; started_at: string }>((a, b) =>
        sb.from("laps").select("game,car,track_key,lap_time_ms,valid,started_at").range(a, b));
      const by = new Map<string, Combo>();
      for (const r of rows) {
        const c = by.get(key(r)) ?? { game: r.game, car: r.car, track_key: r.track_key, laps: 0, valid_laps: 0, best_ms: null, last_driven: 0 };
        c.laps! += 1;
        if (r.valid) {
          c.valid_laps! += 1;
          c.best_ms = c.best_ms == null ? r.lap_time_ms : Math.min(c.best_ms, r.lap_time_ms);
        }
        c.last_driven = Math.max(c.last_driven ?? 0, unix(r.started_at));
        by.set(key(r), c);
      }
      return [...by.values()].sort((x, y) => (y.last_driven ?? 0) - (x.last_driven ?? 0));
    },

    geometry: trackGeometry,

    async laps(c) {
      return (await comboLaps(c)).map<LapSummary>((r) => ({
        id: r.id, game: r.game, car: r.car, track_key: r.track_key, lap_number: r.lap_number,
        lap_time_ms: r.lap_time_ms, valid: r.valid, out_lap: r.out_lap, started_at: unix(r.started_at), sector_ms: r.sector_ms,
      }));
    },

    async corners(lapId, compareId, combo): Promise<CornerReport> {
      if (!combo && lapId !== null) {
        const { data } = await sb.from("laps").select("game,car,track_key").eq("id", lapId).maybeSingle();
        combo = (data as Combo) ?? null;
      }
      if (!combo) throw new Error("No laps yet");
      const [rows, geo, profile] = await Promise.all([comboLaps(combo), trackGeometry(combo), carProfile(combo)]);
      const laps: HubLap[] = rows.map((r) => ({
        id: r.id, lap_number: r.lap_number, lap_time_ms: r.lap_time_ms, valid: r.valid,
        started_at: unix(r.started_at), sector_ms: r.sector_ms, corners: r.corners ?? null, systems: r.systems ?? null,
      }));
      const valid = laps.filter((l) => l.valid);
      const shown = lapId ?? [...valid].sort((a, b) => b.started_at - a.started_at)[0]?.id ?? null;
      const best = [...valid].sort((a, b) => a.lap_time_ms - b.lap_time_ms || a.id - b.id)[0]?.id ?? null;
      const tr = new Map<number, Trace>();
      for (const id of [shown, best]) {
        if (id === null) continue;
        const t = await trace(id);
        if (t) tr.set(id, t);
      }
      const empty: TrackGeometry = { track_key: combo.track_key, length_m: 0, source: "laps", has_edges: false, progress: [], center: [], left: [], right: [], corners: [], sections: [], chapters: [], practice: [] };
      return buildReport({ ...combo, laps, geometry: geo ?? empty, profile, traces: tr }, lapId, compareId);
    },

    trace: (id) => trace(id),
    // Worked out on the rig PC; the hub gets its per-corner numbers with each lap.
    optimal: async () => null,
  };
}
