import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Trace } from "../lib/profile";
import type { CornerReport } from "../lib/types";
import { buildReport, type HubLap } from "./report";

// Made by rig/tests/make_hub_fixture.py: demo laps as uploaded, plus the rig's own reports.
const fx = JSON.parse(readFileSync(new URL("./__fixtures__/demo.json", import.meta.url), "utf8"));
const laps: HubLap[] = fx.laps.map((l: HubLap & { trace: Trace | null }) => ({ ...l, trace: undefined }));
const traces = new Map<number, Trace>(fx.laps.filter((l: { trace: Trace | null }) => l.trace).map((l: { id: number; trace: Trace }) => [l.id, l.trace]));
const input = { game: fx.game, car: fx.car, track_key: fx.track_key, laps, geometry: fx.geometry, profile: fx.profile, traces };

describe("hub report matches the rig's", () => {
  for (const c of fx.cases as { lap_id: number | null; compare_id: number | null; report: CornerReport }[]) {
    it(`lap ${c.lap_id ?? "latest"} vs ${c.compare_id ?? "auto"}`, () => {
      const py = c.report;
      const ts = buildReport(input, c.lap_id, c.compare_id);
      expect(ts.lap_id).toBe(py.lap_id);
      expect(ts.reference_lap_id).toBe(py.reference_lap_id);
      expect(ts.compare_lap_id).toBe(py.compare_lap_id);
      expect(ts.compare_label).toBe(py.compare_label);
      expect(ts.theoretical_best_ms).toBe(py.theoretical_best_ms);
      expect(ts.car_systems).toEqual(py.car_systems);
      expect(ts.systems).toEqual(py.systems);
      expect(ts.lap?.length).toBe(py.lap?.length);
      py.lap?.forEach((pc, i) => {
        const tc = ts.lap![i];
        expect(tc.corner).toBe(pc.corner);
        expect(tc.notes ?? []).toEqual(pc.notes ?? []);
        expect(tc.vs_s ?? null).toBeCloseTo(pc.vs_s ?? 0, 3);
        expect(tc.loss_s ?? 0).toBeCloseTo(pc.loss_s ?? 0, 3);
        expect(tc.advice).toEqual(pc.advice);
      });
      const pm = new Map(py.mastery.map((m) => [m.corner, m]));
      for (const m of ts.mastery) {
        expect(m.grade).toBe(pm.get(m.corner)?.grade);
        expect(m.best_s).toBeCloseTo(pm.get(m.corner)!.best_s, 3);
      }
      // Section times: the hub has telemetry at 20 a second, the rig at 60, so allow a little.
      py.practice.forEach((pp, i) => {
        const tp = ts.practice[i];
        expect(tp.name).toBe(pp.name);
        for (const k of ["time_s", "ref_s"] as const) {
          if (pp[k] == null) expect(tp[k]).toBeNull();
          else expect(Math.abs((tp[k] ?? 0) - pp[k]!)).toBeLessThan(0.06);
        }
      });
    });
  }

  it("covers comparisons with notes", () => {
    const notes = fx.cases.flatMap((c: { report: CornerReport }) => (c.report.lap ?? []).flatMap((x) => x.notes ?? []));
    expect(notes.length).toBeGreaterThan(0);
  });
});
