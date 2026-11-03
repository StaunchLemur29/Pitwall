import { useEffect, useMemo, useRef } from "react";
import { rig, useRig } from "../lib/rig";
import { indexAt, type P } from "../lib/track";
import type { Live, TrackGeometry } from "../lib/types";
import { Card, useSize } from "./common";

// The view zooms so the next corner (plus a bit of its exit) is always on
// screen: between MIN_AHEAD and MAX_AHEAD metres in front of the car.
const MIN_AHEAD = 90;
const MAX_AHEAD = 320;
const BEHIND_M = 120; // road drawn behind the car
const EXTRAP_MAX_S = 0.15; // how far ahead we predict between updates
const BLEND_S = 0.07; // corrections from a new update fade in over this long instead of snapping
const SNAP_M = 4; // bigger corrections than this (a reset, a rewind) jump straight there

interface Scene {
  left: P[];
  right: P[];
  center: P[];
  ref: P[][]; // best-lap line, split where it jumps
  brake: [P, P] | null;
  labels: { text: string; at: P }[];
  hasEdges: boolean;
}

/**
 * Heading-up close-up of the road ahead: real track edges, your best lap's
 * line, the braking point, and your car pointing where it actually points.
 *
 * Drawn on a canvas every display frame (cheap), predicting the car's position
 * from its velocity between telemetry updates so motion stays smooth.
 */
export function TurnByTurn() {
  const g = useRig((s) => s.track);
  const tl = useRig((s) => s.live.track);
  const f = useRig((s) => s.live.frame);
  const ref = useRig((s) => s.refTrace);
  const [box, { w, h }] = useSize<HTMLDivElement>();
  const canvas = useRef<HTMLCanvasElement>(null);
  const gaugeCar = useRef<HTMLDivElement>(null);

  const live = !!g && !!tl && !!f?.world && f.status === "live";
  const p = tl?.p ?? 0;
  const bucket = g ? Math.floor((p * g.length_m) / 25) : 0; // rebuild the visible stretch every ~25 m

  const scene = useRef<Scene | null>(null);
  const c = tl?.corner;
  const brakeIdx = c && c.brake_in_m !== null && g?.has_edges && tl ? indexAt(g, tl.p + c.brake_in_m / g.length_m) : -1;
  useMemo(() => {
    scene.current = g ? buildScene(g, p, ref, brakeIdx) : null;
  }, [g, bucket, ref, brakeIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  const anim = useRef({
    x: 0, z: 0, vx: 0, vz: 0, at: 0,
    ox: 0, oz: 0, oAt: 0, // correction still being blended in
    view: 0, viewSet: false, idx: -1, u: -1,
    car: null as number | null, carRate: 0, carAt: 0,
    ahead: 150, aheadTarget: 150, live: false,
  });
  const geo = useRef(g);
  geo.current = g;

  // Every telemetry frame feeds the animator directly (no React redraw).
  useEffect(() => {
    const feed = (lv: Live) => {
      const gg = geo.current;
      const fr = lv.frame;
      const t = lv.track;
      const a = anim.current;
      const wasLive = a.live;
      a.live = !!gg && !!fr?.world && !!t && fr.status === "live";
      if (!gg || !fr?.world || !t || !a.live) return;
      const now = performance.now();
      const vx = fr.velocity ? fr.velocity[0] : 0;
      const vz = fr.velocity ? fr.velocity[2] : 0;
      if (fr.world[0] !== a.x || fr.world[2] !== a.z || !wasLive) {
        // Where we're drawing the car right now, before taking the new sample.
        const shown = predict(a, now);
        a.x = fr.world[0];
        a.z = fr.world[2];
        a.vx = vx;
        a.vz = vz;
        // Predict from when the game actually moved the car, not when we heard.
        a.at = now - Math.max(0, Math.min(100, lv.pos_age_ms ?? 0));
        const fresh = predict({ ...a, ox: 0, oz: 0 }, now);
        const ex = shown[0] - fresh[0];
        const ez = shown[1] - fresh[1];
        if (wasLive && ex * ex + ez * ez < SNAP_M * SNAP_M) {
          a.ox = ex;
          a.oz = ez;
        } else a.ox = a.oz = 0;
        a.oAt = now;
      } else {
        // Same position as last time (the game hasn't drawn a new frame yet):
        // keep predicting from the old sample rather than restarting it.
        a.vx = vx;
        a.vz = vz;
      }
      const c0 = a.idx >= 0 && a.idx < gg.center.length ? gg.center[a.idx] : null;
      if (!c0 || (c0[0] - a.x) ** 2 + (c0[1] - a.z) ** 2 > 40 * 40) a.idx = indexAt(gg, t.p);
      const car = t.car_heading ?? null;
      if (car !== null && a.car !== null && now - a.carAt > 4) {
        const rate = angDiff(car, a.car) / ((now - a.carAt) / 1000);
        a.carRate = Math.abs(rate) > 400 ? 0 : a.carRate * 0.5 + rate * 0.5;
      }
      a.car = car;
      a.carAt = now;
      const k = t.corner;
      const toExit = k ? ((((k.exit - t.p) % 1) + 1) % 1) * gg.length_m : 0;
      const span = k ? (k.distance_m > 0 ? k.distance_m + 90 : toExit + 60) : 150;
      a.aheadTarget = Math.min(MAX_AHEAD, Math.max(MIN_AHEAD, span));
    };
    if (rig.latest) feed(rig.latest);
    return rig.onFrame(feed);
  }, []);

  // Draw loop.
  useEffect(() => {
    const cv = canvas.current;
    if (!cv || w === 0 || h === 0) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    const ctx = cv.getContext("2d", { alpha: false });
    if (!ctx) return;
    const css = getComputedStyle(document.documentElement);
    const col = {
      bg: css.getPropertyValue("--card").trim() || "#14171c",
      road: "#2a2f37",
      edge: "#c9ced6",
      ref: css.getPropertyValue("--best").trim() || "#b980ff",
      brake: css.getPropertyValue("--bad").trim() || "#ff5252",
      accent: css.getPropertyValue("--accent").trim() || "#ff5a36",
      text: "#eef0f3",
    };
    let raf = 0;
    let last = performance.now();
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const a = anim.current;
      const sc = scene.current;
      const gg = geo.current;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const [x, z] = predict(a, now);
      let frac: number | null = null;
      if (gg && a.idx >= 0) {
        a.idx = nearestIndex(gg, x, z, a.idx);
        // Position along the road between centre-line points (continuous, so
        // direction and L/R glide instead of stepping every few metres).
        a.u = projectIndex(gg, x, z, a.idx);
        const roadDir = roadHeading(gg, a.u);
        if (!a.viewSet) {
          a.view = roadDir;
          a.viewSet = true;
        } else a.view += angDiff(roadDir, a.view) * Math.min(1, dt * 20);
        frac = gg.has_edges ? acrossTrack(gg, a.u, x, z) : null;
      }
      a.ahead += (a.aheadTarget - a.ahead) * Math.min(1, dt * 3);

      const cx = w / 2;
      const cy = h * 0.8;
      const scale = (cy - 24) / a.ahead;
      const rot = ((-90 - a.view) * Math.PI) / 180;
      const cos = Math.cos(rot);
      const sin = Math.sin(rot);

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = col.bg;
      ctx.fillRect(0, 0, w, h);
      if (!sc || !a.live) return;

      // World → screen for this frame.
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(rot);
      ctx.scale(scale, scale);
      ctx.translate(-x, -z);
      const px = 1 / scale; // one screen pixel in world units
      if (sc.hasEdges) {
        ctx.beginPath();
        trace(ctx, sc.left);
        for (let i = sc.right.length - 1; i >= 0; i--) ctx.lineTo(sc.right[i][0], sc.right[i][1]);
        ctx.closePath();
        ctx.fillStyle = col.road;
        ctx.fill();
        ctx.lineWidth = 2 * px;
        ctx.strokeStyle = col.edge;
        ctx.beginPath();
        trace(ctx, sc.left);
        trace(ctx, sc.right);
        ctx.stroke();
      } else {
        ctx.lineWidth = 6 * px;
        ctx.strokeStyle = col.edge;
        ctx.globalAlpha = 0.6;
        ctx.beginPath();
        trace(ctx, sc.center);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (sc.ref.length) {
        ctx.setLineDash([8 * px, 6 * px]);
        ctx.lineWidth = 3 * px;
        ctx.strokeStyle = col.ref;
        ctx.beginPath();
        for (const seg of sc.ref) trace(ctx, seg);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (sc.brake) {
        ctx.lineWidth = 6 * px;
        ctx.strokeStyle = col.brake;
        ctx.beginPath();
        ctx.moveTo(sc.brake[0][0], sc.brake[0][1]);
        ctx.lineTo(sc.brake[1][0], sc.brake[1][1]);
        ctx.stroke();
      }
      ctx.restore();

      // Screen-space bits: upright labels and the car.
      ctx.font = `800 ${Math.round(Math.max(14, w * 0.026))}px "Inter Variable", system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.lineWidth = 5;
      ctx.strokeStyle = col.bg;
      ctx.fillStyle = col.text;
      for (const l of sc.labels) {
        const wx = (l.at[0] - x) * scale;
        const wz = (l.at[1] - z) * scale;
        const sx = cx + wx * cos - wz * sin;
        const sy = cy + wx * sin + wz * cos;
        ctx.strokeText(l.text, sx, sy);
        ctx.fillText(l.text, sx, sy);
      }
      const carRot = a.car === null ? 0 : a.car + a.carRate * Math.min(EXTRAP_MAX_S, (now - a.carAt) / 1000) - a.view;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate((carRot * Math.PI) / 180);
      ctx.beginPath();
      ctx.moveTo(0, -16);
      ctx.lineTo(10, 12);
      ctx.lineTo(0, 6);
      ctx.lineTo(-10, 12);
      ctx.closePath();
      ctx.fillStyle = col.accent;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = col.bg;
      ctx.stroke();
      ctx.restore();

      if (gaugeCar.current && frac !== null) {
        gaugeCar.current.style.left = `${Math.max(-0.05, Math.min(1.05, frac)) * 100}%`;
      }
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [w, h]);

  if (!g) {
    return (
      <Card title="Road ahead" dim>
        <div className="upcoming">The close-up view appears once the track layout loads.</div>
      </Card>
    );
  }
  return (
    <Card title={c ? c.label : "Road ahead"} right={live && tl?.frac != null ? <span className="pill">{sideText(tl.frac)}</span> : null}>
      <div ref={box} className="tbt">
        <canvas ref={canvas} style={{ width: w, height: h }} />
      </div>
      {ref?.x && <div className="tbt__legend"><i /> your best lap's line</div>}
      {live && tl?.frac != null && <WidthGauge frac={tl.frac} carRef={gaugeCar} />}
    </Card>
  );
}

function trace(ctx: CanvasRenderingContext2D, pts: P[]) {
  if (!pts.length) return;
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
}

/** Everything in world coordinates for the stretch around the car. */
function buildScene(g: TrackGeometry, p: number, ref: Record<string, number[]> | null, brakeIdx: number): Scene {
  const n = g.center.length;
  const step = g.length_m / n;
  const i0 = indexAt(g, p);
  const idx: number[] = [];
  for (let k = -Math.ceil(BEHIND_M / step); k <= Math.ceil((MAX_AHEAD + 200) / step); k++) idx.push((((i0 + k) % n) + n) % n);
  const lo = p - BEHIND_M / g.length_m;
  const hi = p + (MAX_AHEAD + 150) / g.length_m;
  const refSegs: P[][] = [];
  if (ref?.x) {
    let cur: P[] = [];
    ref.p.forEach((q, i) => {
      if ((ref.t[i] < 5 && q > 0.9) || !inRange(q, lo, hi)) {
        if (cur.length > 1) refSegs.push(cur);
        cur = [];
        return;
      }
      const pt: P = [ref.x[i], ref.z[i]];
      const prev = cur[cur.length - 1];
      if (prev && (pt[0] - prev[0]) ** 2 + (pt[1] - prev[1]) ** 2 > 25 * 25) {
        if (cur.length > 1) refSegs.push(cur);
        cur = [];
      }
      cur.push(pt);
    });
    if (cur.length > 1) refSegs.push(cur);
  }
  const labels = g.corners
    .filter((k) => {
      const ahead = ((((k.apex - p) % 1) + 1) % 1) * g.length_m;
      return ahead > 0 && ahead < MAX_AHEAD + 60;
    })
    .map((k) => ({ text: `${k.direction}${k.grade}`, at: g.center[indexAt(g, k.apex)] as P }));
  return {
    left: g.has_edges ? idx.map((i) => g.left[i] as P) : [],
    right: g.has_edges ? idx.map((i) => g.right[i] as P) : [],
    center: idx.map((i) => g.center[i] as P),
    ref: refSegs,
    brake: brakeIdx >= 0 ? [g.left[brakeIdx] as P, g.right[brakeIdx] as P] : null,
    labels,
    hasEdges: g.has_edges,
  };
}

function nearestIndex(g: TrackGeometry, x: number, z: number, hint: number): number {
  const n = g.center.length;
  let best = hint;
  let bestD = Infinity;
  for (let k = -25; k <= 40; k++) {
    const i = (((hint + k) % n) + n) % n;
    const c = g.center[i];
    const d = (c[0] - x) ** 2 + (c[1] - z) ** 2;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

interface Motion {
  x: number; z: number; vx: number; vz: number; at: number;
  ox: number; oz: number; oAt: number;
}

/** Where the car is at `now`: last sample moved on by its velocity, plus any correction still fading out. */
function predict(a: Motion, now: number): [number, number] {
  const lead = Math.min(EXTRAP_MAX_S, Math.max(0, (now - a.at) / 1000));
  const fade = Math.exp(-Math.max(0, now - a.oAt) / 1000 / BLEND_S);
  return [a.x + a.vx * lead + a.ox * fade, a.z + a.vz * lead + a.oz * fade];
}

/** Point on a polyline at a fractional index (wraps around the lap). */
function pointAt(pts: number[][], u: number): P {
  const n = pts.length;
  const i = Math.floor(u);
  const t = u - i;
  const a = pts[((i % n) + n) % n];
  const b = pts[(((i + 1) % n) + n) % n];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** Fractional centre-line index of the car, from the nearest point and its two neighbouring segments. */
function projectIndex(g: TrackGeometry, x: number, z: number, i: number): number {
  const n = g.center.length;
  let best = i;
  let bestD = Infinity;
  for (const s of [i - 1, i]) {
    const a = g.center[((s % n) + n) % n];
    const b = g.center[(((s + 1) % n) + n) % n];
    const dx = b[0] - a[0];
    const dz = b[1] - a[1];
    const l2 = dx * dx + dz * dz;
    const t = l2 > 0 ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (z - a[1]) * dz) / l2)) : 0;
    const px = a[0] + dx * t - x;
    const pz = a[1] + dz * t - z;
    const d = px * px + pz * pz;
    if (d < bestD) {
      bestD = d;
      best = s + t;
    }
  }
  return ((best % n) + n) % n;
}

function roadHeading(g: TrackGeometry, u: number): number {
  const a = pointAt(g.center, u - 4);
  const b = pointAt(g.center, u + 4);
  return (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
}

function acrossTrack(g: TrackGeometry, u: number, x: number, z: number): number {
  const l = pointAt(g.left, u);
  const r = pointAt(g.right, u);
  const wx = r[0] - l[0];
  const wz = r[1] - l[1];
  const w2 = wx * wx + wz * wz;
  return w2 > 0 ? ((x - l[0]) * wx + (z - l[1]) * wz) / w2 : 0.5;
}

function inRange(q: number, lo: number, hi: number): boolean {
  const span = (((hi - lo) % 1) + 1) % 1;
  return ((((q - lo) % 1) + 1) % 1) <= span;
}

function angDiff(a: number, b: number): number {
  return ((((a - b + 180) % 360) + 360) % 360) - 180;
}

function sideText(frac: number): string {
  if (frac < 0 || frac > 1) return "off track";
  if (frac < 0.2) return "left edge";
  if (frac > 0.8) return "right edge";
  return frac < 0.4 ? "left of centre" : frac > 0.6 ? "right of centre" : "centre";
}

function WidthGauge({ frac, carRef }: { frac: number; carRef: React.RefObject<HTMLDivElement> }) {
  const x = Math.max(-0.05, Math.min(1.05, frac));
  return (
    <div className="wgauge" aria-label="Position across the track">
      <span>L</span>
      <div className="wgauge__bar">
        <div ref={carRef} className="wgauge__car" style={{ left: `${x * 100}%` }} />
      </div>
      <span>R</span>
    </div>
  );
}
