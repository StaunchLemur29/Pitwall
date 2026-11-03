/** Laps grouped into sessions (driving more than an hour apart starts a new one). */
import type { LapSummary } from "../lib/types";

export const SESSION_GAP_S = 60 * 60; // laps more than an hour apart start a new session

export interface Session {
  start: number;
  laps: LapSummary[]; // valid laps, in order
  all: number; // every lap, valid or not
  best: number;
  median: number;
  spread: number; // standard deviation of valid laps (ms)
}

export function sessionsOf(laps: LapSummary[]): Session[] {
  const sorted = [...laps].sort((a, b) => a.started_at - b.started_at);
  const groups: LapSummary[][] = [];
  for (const l of sorted) {
    const g = groups[groups.length - 1];
    if (g && l.started_at - g[g.length - 1].started_at <= SESSION_GAP_S) g.push(l);
    else groups.push([l]);
  }
  return groups
    .map((g) => {
      const v = g.filter((l) => l.valid).map((l) => l.lap_time_ms);
      if (!v.length) return null;
      const s = [...v].sort((a, b) => a - b);
      const median = s.length % 2 ? s[s.length >> 1] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
      const mean = v.reduce((a, b) => a + b, 0) / v.length;
      const spread = Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / v.length);
      return { start: g[0].started_at, laps: g.filter((l) => l.valid), all: g.length, best: s[0], median, spread };
    })
    .filter((x): x is Session => x !== null);
}

