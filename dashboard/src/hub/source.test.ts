import { describe, expect, it } from "vitest";
import { hubSource } from "./source";

// A stand-in for the Supabase client: each table's rows, filtered by .eq().
function fakeSb(tables: Record<string, Record<string, unknown>[]>) {
  const query = (rows: Record<string, unknown>[]) => {
    const q = {
      select: () => q,
      eq: (k: string, v: unknown) => query(rows.filter((r) => r[k] === v)),
      order: () => q,
      range: (a: number, b: number) => Promise.resolve({ data: rows.slice(a, b + 1), error: null }),
      maybeSingle: () => Promise.resolve({ data: rows[0] ?? null, error: null }),
    };
    return q;
  };
  return { from: (t: string) => query(tables[t] ?? []), functions: { invoke: async () => ({ data: null }) } } as never;
}

const combo = { game: "ac", car: "c", track_key: "t" };

describe("hub source", () => {
  it("keeps each lap's section passes and conditions, and reads the optimal run and drill bests", async () => {
    const lap = {
      id: 1, ...combo, lap_number: 1, lap_time_ms: 60000, valid: true, out_lap: false, started_at: "2026-11-05T10:00:00Z",
      sector_ms: [], corners: [], systems: null, review: null, time_to_beat: null,
      sections: [[0.1, 0.2, 9500]], conditions: { road_c: 31 },
    };
    const geometry = { track_key: "t", length_m: 1000, source: "game", has_edges: false, progress: [], center: [], left: [], right: [],
      corners: [], sections: [], chapters: [], practice: [{ number: 1, name: "S1", start: 0.1, end: 0.2, corners: [] }] };
    const src = hubSource(fakeSb({
      laps: [lap],
      tracks: [{ ...combo, geometry }],
      combo_extras: [{ ...combo, optimal: { lap_s: 58.2, trace: { t: [0], p: [0] } }, drill_bests: [[0.1, 0.2, 9100]] }],
    }));
    const rep = await src.corners(1, null, combo as never);
    expect(rep.conditions).toEqual({ road_c: 31 });
    expect(rep.practice[0].drill_best_s).toBe(9.1); // the drill run beats the lap pass
    expect(rep.optimal?.lap_s).toBe(58.2);
    expect((await src.optimal(combo as never))?.lap_s).toBe(58.2);
  });
});
