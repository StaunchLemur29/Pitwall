import { describe, expect, it } from "vitest";
import { keepRecentAndFastest } from "./lapList";
import type { LapSummary } from "./types";

const lap = (id: number, ms: number, valid = true, rewound = false) =>
  ({ id, lap_time_ms: ms, valid, rewound, lap_number: id }) as unknown as LapSummary;

describe("keepRecentAndFastest", () => {
  it("keeps an old best lap after many newer laps", () => {
    const newer = Array.from({ length: 150 }, (_, i) => lap(1000 - i, 70_000 + i));
    const out = keepRecentAndFastest([...newer, lap(1, 60_000)]);
    expect(out.length).toBe(101);
    expect(out.some((l) => l.id === 1)).toBe(true);
  });
  it("doesn't keep old invalid or rewound laps for their time", () => {
    const newer = Array.from({ length: 120 }, (_, i) => lap(1000 - i, 70_000 + i));
    const out = keepRecentAndFastest([...newer, lap(1, 50_000, false), lap(2, 50_000, true, true)]);
    expect(out.some((l) => l.id === 1 || l.id === 2)).toBe(false);
  });
});
