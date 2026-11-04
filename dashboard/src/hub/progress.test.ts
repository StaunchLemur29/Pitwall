import { describe, expect, it } from "vitest";
import type { LapSummary } from "../lib/types";
import { sessionsOf } from "./sessions";

const lap = (id: number, at: number, ms: number, valid = true): LapSummary => ({
  id, game: "ac", car: "c", track_key: "t", lap_number: id, lap_time_ms: ms, valid, out_lap: false, started_at: at, sector_ms: [],
});

describe("sessions", () => {
  it("splits laps more than an hour apart and summarises each session", () => {
    const day = 86400;
    const s = sessionsOf([
      lap(1, 1000, 92000, false), // out lap
      lap(2, 1100, 91000),
      lap(3, 1200, 90000),
      lap(4, 1300, 92000),
      lap(5, day + 1000, 89500),
      lap(6, day + 1100, 89700),
      lap(7, 3 * day, 95000, false), // a session with no clean laps is left out
    ]);
    expect(s.map((x) => x.laps.length)).toEqual([3, 2]);
    expect(s[0]).toMatchObject({ all: 4, best: 90000, median: 91000 });
    expect(s[0].spread).toBeCloseTo(816.5, 1);
    expect(s[1].best).toBe(89500);
  });
});
