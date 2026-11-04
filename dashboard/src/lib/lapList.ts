import type { LapSummary } from "./types";

/** The newest 100 laps, plus your 10 fastest clean ones however old: the
 * analysis compares with faster laps, so your best must stay in the list. */
export function keepRecentAndFastest(laps: LapSummary[], recent = 100, fastest = 10): LapSummary[] {
  const keep = new Set(
    laps
      .filter((l) => l.valid && !l.rewound)
      .sort((a, b) => a.lap_time_ms - b.lap_time_ms)
      .slice(0, fastest)
      .map((l) => l.id),
  );
  return laps.filter((l, i) => i < recent || keep.has(l.id));
}
