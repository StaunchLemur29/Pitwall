/**
 * A lap trace resampled onto a distance grid around one corner, so two laps
 * can be compared metre by metre. x is metres from the apex (negative before).
 */
export type Trace = Record<string, number[]>;

export interface Profile {
  x: number[];
  t: number[];
  speed: number[];
  brake: number[];
  gas: number[];
  gear: number[];
  wx: number[];
  wz: number[];
}

const FIELDS = ["t", "speed", "brake", "gas", "gear", "wx", "wz"] as const;

export function profile(tr: Trace | null, apexP: number, lengthM: number, from: number, to: number, step = 2): Profile | null {
  if (!tr?.p?.length) return null;
  const lapEnd = Math.max(...tr.t);
  const raw: { x: number; t: number; speed: number; brake: number; gas: number; gear: number; wx: number; wz: number }[] = [];
  for (let i = 0; i < tr.p.length; i++) {
    const p = tr.p[i];
    if (tr.t[i] < 5 && p > 0.9) continue; // still before the line at the start
    let rel = p - apexP;
    rel -= Math.round(rel); // nearest way round the lap
    const x = rel * lengthM;
    if (x < from - 20 || x > to + 20) continue;
    // A corner near the line: the part on the far side of it was driven at
    // the other end of the lap, so shift its time to keep the clock running.
    const t = p - apexP > 0.5 ? tr.t[i] - lapEnd : apexP - p > 0.5 ? tr.t[i] + lapEnd : tr.t[i];
    raw.push({ x, t, speed: tr.speed[i], brake: tr.brake[i], gas: tr.gas[i], gear: tr.gear?.[i] ?? 0, wx: tr.x?.[i] ?? 0, wz: tr.z?.[i] ?? 0 });
  }
  raw.sort((a, b) => a.x - b.x);
  const pts = raw.filter((r, i) => i === 0 || r.x > raw[i - 1].x);
  if (pts.length < 4 || pts[0].x > from + 15 || pts[pts.length - 1].x < to - 15) return null;
  const out: Profile = { x: [], t: [], speed: [], brake: [], gas: [], gear: [], wx: [], wz: [] };
  let j = 0;
  for (let x = from; x <= to + 1e-6; x += step) {
    while (j < pts.length - 2 && pts[j + 1].x < x) j++;
    const a = pts[j];
    const b = pts[j + 1];
    const k = Math.max(0, Math.min(1, (x - a.x) / Math.max(1e-6, b.x - a.x)));
    out.x.push(x);
    for (const f of FIELDS) {
      if (f === "gear") out.gear.push(k < 0.5 ? a.gear : b.gear);
      else out[f].push(a[f] + (b[f] - a[f]) * k);
    }
  }
  return out;
}

/** Running time gained (−) or lost (+) against the other lap, from the start of the window. */
export function timeDelta(mine: Profile, other: Profile): number[] {
  return mine.t.map((t, i) => t - mine.t[0] - (other.t[i] - other.t[0]));
}

/** Track progress → lap time, for whole-lap comparisons. */
export function timeLookup(tr: Trace): (p: number) => number {
  const ps: number[] = [];
  const ts: number[] = [];
  tr.p.forEach((p, i) => {
    if (tr.t[i] < 5 && p > 0.9) return;
    if (!ps.length || p > ps[ps.length - 1]) {
      ps.push(p);
      ts.push(tr.t[i]);
    }
  });
  return (p: number) => {
    let lo = 0;
    let hi = ps.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (ps[mid] < p) lo = mid + 1;
      else hi = mid;
    }
    if (lo === 0) return ts[0];
    const k = (p - ps[lo - 1]) / Math.max(1e-9, ps[lo] - ps[lo - 1]);
    return ts[lo - 1] + k * (ts[lo] - ts[lo - 1]);
  };
}
