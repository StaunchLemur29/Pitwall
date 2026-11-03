import { useEffect, useMemo, useRef } from "react";
import { rig, useRig } from "../lib/rig";
import { indexAt, pathOf, type P } from "../lib/track";
import type { Live, TrackGeometry } from "../lib/types";
import { Card, useSize } from "./common";

// The view zooms so the next corner (plus a bit of its exit) is always on
// screen: between MIN_AHEAD and MAX_AHEAD metres in front of the car.
const MIN_AHEAD = 90;
const MAX_AHEAD = 320;
const BEHIND_M = 120; // road drawn behind the car
const EXTRAP_MAX_S = 0.12; // how far ahead we predict between updates

/**
 * Heading-up close-up of the road ahead: real track edges, your best lap's
 * line, the braking point, and your car pointing where it actually points.
 *
 * Telemetry arrives ~30×/s; the view itself animates every display frame,
 * predicting the car's position from its velocity, so it stays smooth.
 */
export function TurnByTurn() {
  const g = useRig((s) => s.track);
  const tl = useRig((s) => s.live.track);
  const f = useRig((s) => s.live.frame);
  const ref = useRig((s) => s.refTrace);
  const [box, { w, h }] = useSize<HTMLDivElement>();

  const live = !!g && !!tl && !!f?.world && f.status === "live";
  const p = tl?.p ?? 0;
  // Rebuild the visible stretch only when the car has moved ~25 m.
  const bucket = g ? Math.floor((p * g.length_m) / 25) : 0;
  const win = useMemo(() => (g ? windowPaths(g, p) : null), [g, bucket]); // eslint-disable-line react-hooks/exhaustive-deps
  const refPath = useMemo(() => {
    if (!ref?.x || !g) return "";
    const lo = p - BEHIND_M / g.length_m;
    const hi = p + (MAX_AHEAD + 150) / g.length_m;
    // Your best lap's line near the car. Skip the few samples logged just
    // before the start line, and never join points that are far apart.
    let d = "";
    let prev: P | null = null;
    ref.p.forEach((q, i) => {
      if (ref.t[i] < 5 && q > 0.9) return;
      if (!inRange(q, lo, hi)) {
        prev = null;
        return;
      }
      const pt: P = [ref.x[i], ref.z[i]];
      const jump = prev ? (pt[0] - prev[0]) ** 2 + (pt[1] - prev[1]) ** 2 > 25 * 25 : true;
      d += `${jump ? "M" : "L"}${pt[0].toFixed(1)},${pt[1].toFixed(1)}`;
      prev = pt;
    });
    return d;
  }, [ref, g, bucket]); // eslint-disable-line react-hooks/exhaustive-deps

  // Animation state lives in refs: the rAF loop writes straight to the SVG.
  const groupEl = useRef<SVGGElement>(null);
  const carEl = useRef<SVGPathElement>(null);
  const labelsEl = useRef<SVGGElement>(null);
  const anim = useRef({
    x: 0, z: 0, vx: 0, vz: 0, at: 0,
    view: 0, viewSet: false, idx: -1,
    car: null as number | null, carRate: 0, carAt: 0,
    ahead: 150, aheadTarget: 150,
  });
  const gaugeCar = useRef<HTMLDivElement>(null);
  const geo = useRef(g);
  geo.current = g;

  // Feed every telemetry sample into the animator (full rate, no React redraw).
  useEffect(() => {
    const feed = (lv: Live) => {
      const gg = geo.current;
      const f = lv.frame;
      const tl = lv.track;
      if (!gg || !f?.world || !tl || f.status !== "live") return;
      const a = anim.current;
      a.x = f.world[0];
      a.z = f.world[2];
      a.vx = f.velocity ? f.velocity[0] : 0;
      a.vz = f.velocity ? f.velocity[2] : 0;
      const now = performance.now();
      a.at = now;
      // (Re)find ourselves on the outline at start, after a rewind or a new track.
      const c0 = a.idx >= 0 && a.idx < gg.center.length ? gg.center[a.idx] : null;
      if (!c0 || (c0[0] - a.x) ** 2 + (c0[1] - a.z) ** 2 > 40 * 40) a.idx = indexAt(gg, tl.p);
      const car = tl.car_heading ?? null;
      if (car !== null && a.car !== null && now > a.carAt) {
        a.carRate = angDiff(car, a.car) / ((now - a.carAt) / 1000);
      }
      a.car = car;
      a.carAt = now;
      const c = tl.corner;
      const toExit = c ? ((((c.exit - tl.p) % 1) + 1) % 1) * gg.length_m : 0;
      const span = c ? (c.distance_m > 0 ? c.distance_m + 90 : toExit + 60) : 150;
      a.aheadTarget = Math.min(MAX_AHEAD, Math.max(MIN_AHEAD, span));
    };
    if (rig.latest) feed(rig.latest);
    return rig.onFrame(feed);
  }, []);

  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const frame = (now: number) => {
      const a = anim.current;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const lead = Math.min(EXTRAP_MAX_S, (now - a.at) / 1000);
      const x = a.x + a.vx * lead;
      const z = a.z + a.vz * lead;
      // Road direction and left/right position are worked out here, every
      // display frame, from the predicted position — no waiting, no lag.
      const gg = geo.current;
      let frac: number | null = null;
      if (gg && a.idx >= 0) {
        a.idx = nearestIndex(gg, x, z, a.idx);
        const roadDir = roadHeading(gg, a.idx);
        // Only a whisper of smoothing, to hide the 3 m steps in the outline.
        if (!a.viewSet) {
          a.view = roadDir;
          a.viewSet = true;
        } else a.view += angDiff(roadDir, a.view) * Math.min(1, dt * 25);
        frac = gg.has_edges ? acrossTrack(gg, a.idx, x, z) : null;
      }
      a.ahead += (a.aheadTarget - a.ahead) * Math.min(1, dt * 3);
      const cx = w / 2;
      const cy = h * 0.8;
      const scale = h > 0 ? (cy - 24) / a.ahead : 1;
      const rot = -90 - a.view;
      groupEl.current?.setAttribute("transform", `translate(${cx},${cy}) rotate(${rot}) scale(${scale}) translate(${-x},${-z})`);
      const carLead = Math.min(EXTRAP_MAX_S, (now - a.carAt) / 1000);
      const carRot = a.car === null ? 0 : a.car + a.carRate * carLead - a.view;
      if (gaugeCar.current && frac !== null) {
        gaugeCar.current.style.left = `${Math.max(-0.05, Math.min(1.05, frac)) * 100}%`;
      }
      carEl.current?.setAttribute("transform", `translate(${cx},${cy}) rotate(${carRot})`);
      // Corner labels stay upright: place them in screen space.
      const rad = (rot * Math.PI) / 180;
      labelsEl.current?.querySelectorAll<SVGTextElement>("text").forEach((t) => {
        const wx = Number(t.dataset.x) - x;
        const wz = Number(t.dataset.z) - z;
        t.setAttribute("x", String(cx + (wx * Math.cos(rad) - wz * Math.sin(rad)) * scale));
        t.setAttribute("y", String(cy + (wx * Math.sin(rad) + wz * Math.cos(rad)) * scale));
      });
      raf = requestAnimationFrame(frame);
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

  const c = tl?.corner;
  let brake: [P, P] | null = null;
  if (c && c.brake_in_m !== null && g.has_edges && tl) {
    const i = indexAt(g, tl.p + c.brake_in_m / g.length_m);
    brake = [g.left[i] as P, g.right[i] as P];
  }
  const labels = live
    ? g.corners.filter((k) => {
        const ahead = ((((k.apex - p) % 1) + 1) % 1) * g.length_m;
        return ahead > 0 && ahead < MAX_AHEAD + 60;
      })
    : [];

  return (
    <Card title={c ? c.label : "Road ahead"} right={live && tl?.frac != null ? <span className="pill">{sideText(tl.frac)}</span> : null}>
      <div ref={box} className="tbt">
        {w > 0 && win && (
          <svg width={w} height={h}>
            <g ref={groupEl}>
              <path d={win.road} className="tbt__road" />
              <path d={win.left} className="tbt__edge" vectorEffect="non-scaling-stroke" />
              <path d={win.right} className="tbt__edge" vectorEffect="non-scaling-stroke" />
              {!g.has_edges && <path d={win.center} className="tbt__learnt" vectorEffect="non-scaling-stroke" />}
              {refPath && <path d={refPath} className="tbt__ref" vectorEffect="non-scaling-stroke" />}
              {brake && (
                <line x1={brake[0][0]} y1={brake[0][1]} x2={brake[1][0]} y2={brake[1][1]} className="tbt__brake" vectorEffect="non-scaling-stroke" />
              )}
            </g>
            <g ref={labelsEl}>
              {labels.map((k) => {
                const at = g.center[indexAt(g, k.apex)];
                return (
                  <text key={k.number} data-x={at[0]} data-z={at[1]} className="tbt__label" textAnchor="middle">
                    {k.direction}
                    {k.grade}
                  </text>
                );
              })}
            </g>
            {live && <path ref={carEl} d="M0,-16 L10,12 L0,6 L-10,12 Z" className="tbt__car" />}
          </svg>
        )}
      </div>
      {refPath && <div className="tbt__legend"><i /> your best lap's line</div>}
      {live && tl?.frac != null && <WidthGauge frac={tl.frac} carRef={gaugeCar} />}
    </Card>
  );
}

/** The road from a bit behind the car to the farthest we might zoom out to. */
function windowPaths(g: TrackGeometry, p: number) {
  const n = g.center.length;
  const step = g.length_m / n;
  const i0 = indexAt(g, p);
  const back = Math.ceil(BEHIND_M / step);
  const fwd = Math.ceil((MAX_AHEAD + 200) / step);
  const idx: number[] = [];
  for (let k = -back; k <= fwd; k++) idx.push((((i0 + k) % n) + n) % n);
  const left = idx.map((i) => g.left[i] as P);
  const right = idx.map((i) => g.right[i] as P);
  const center = idx.map((i) => g.center[i] as P);
  return {
    road: g.has_edges ? `${pathOf(left)}L${right.reverse().map(([x, z]) => `${x},${z}`).join("L")}Z` : "",
    left: g.has_edges ? pathOf(idx.map((i) => g.left[i] as P)) : "",
    right: g.has_edges ? pathOf(idx.map((i) => g.right[i] as P)) : "",
    center: pathOf(center),
  };
}

/** Nearest outline point to (x, z), searching around the last one. */
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

/** Road direction (map degrees) averaged over ±12 m, so it turns smoothly. */
function roadHeading(g: TrackGeometry, i: number): number {
  const n = g.center.length;
  const a = g.center[(((i - 4) % n) + n) % n];
  const b = g.center[(i + 4) % n];
  return (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
}

/** 0 at the left edge, 1 at the right edge (beyond = off track). */
function acrossTrack(g: TrackGeometry, i: number, x: number, z: number): number {
  const l = g.left[i];
  const r = g.right[i];
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

/** A strip across the track: left edge → right edge, with your car on it. */
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
