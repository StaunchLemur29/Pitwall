// Helpers for drawing a TrackGeometry.

import type { TrackGeometry } from "./types";

export type P = [number, number];

/** Index into geometry arrays nearest to a lap progress value. */
export function indexAt(g: TrackGeometry, progress: number): number {
  const ps = g.progress;
  const p = ((progress % 1) + 1) % 1;
  let lo = 0;
  let hi = ps.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ps[mid] < p) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function pathOf(pts: P[], close = false): string {
  if (!pts.length) return "";
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) d += `L${pts[i][0].toFixed(1)},${pts[i][1].toFixed(1)}`;
  return close ? `${d}Z` : d;
}

/** The track surface as one closed path (left edge forwards, right edge back). */
export function ribbonPath(g: TrackGeometry, map: (p: P) => P = (p) => p): string {
  if (!g.has_edges || !g.left.length) return "";
  return `${pathOf(g.left.map(map), true)}${pathOf(g.right.map(map), true)}`;
}

/** Points of the centre line between two progress values (handles wrap). */
export function slice(g: TrackGeometry, from: number, to: number, which: "center" | "left" | "right" = "center"): P[] {
  const a = indexAt(g, from);
  const b = indexAt(g, to);
  const arr = g[which];
  if (a <= b) return arr.slice(a, b + 1) as P[];
  return [...arr.slice(a), ...arr.slice(0, b + 1)] as P[];
}

export const GRADE_COLORS: Record<string, string> = {
  green: "var(--good)",
  amber: "var(--warn)",
  red: "var(--bad)",
  new: "var(--faint)",
};
