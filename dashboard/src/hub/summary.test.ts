import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Trace } from "../lib/profile";
import { buildReport, type HubLap } from "./report";
import { debriefLap, fmtMs, sessionSummary } from "./summary";

// Made by rig/tests/make_hub_fixture.py, with the rig's own session_summary of the same laps.
const fx = JSON.parse(readFileSync(new URL("./__fixtures__/demo.json", import.meta.url), "utf8"));
const laps: HubLap[] = fx.laps.map((l: HubLap & { trace: Trace | null }) => ({ ...l, trace: undefined }));
const traces = new Map<number, Trace>(fx.laps.filter((l: { trace: Trace | null }) => l.trace).map((l: { id: number; trace: Trace }) => [l.id, l.trace]));
const input = { game: fx.game, car: fx.car, track_key: fx.track_key, laps, geometry: fx.geometry, profile: fx.profile, traces };

/** Same values, numbers within 0.01 (section times use 20 Hz telemetry on the hub). */
function close(a: unknown, b: unknown, path = ""): void {
  if (typeof a === "number" && typeof b === "number") {
    expect(Math.abs(a - b), path).toBeLessThan(0.011);
  } else if (Array.isArray(a) && Array.isArray(b)) {
    expect(a.length, path).toBe(b.length);
    a.forEach((x, i) => close(x, b[i], `${path}[${i}]`));
  } else if (a && b && typeof a === "object" && typeof b === "object") {
    expect(Object.keys(a).sort(), path).toEqual(Object.keys(b).sort());
    for (const k of Object.keys(a)) close((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k], `${path}.${k}`);
  } else {
    expect(a, path).toEqual(b);
  }
}

describe("debrief summary matches the rig's", () => {
  it("builds the same session summary", () => {
    const best = debriefLap(laps)!;
    expect(best).not.toBeNull();
    const rep = buildReport(input, best.id, null);
    const ts = sessionSummary(fx.car, fx.track_key, laps, rep, fx.geometry);
    close(ts, fx.session_summary);
  });

  it("needs three clean laps", () => {
    expect(debriefLap(laps.filter((l) => !l.valid))).toBeNull();
  });

  it("formats lap times like Python", () => {
    expect(fmtMs(57441)).toBe("0:57.441");
    expect(fmtMs(60616)).toBe("1:00.616");
  });
});
