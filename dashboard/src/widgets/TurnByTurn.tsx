import { useEffect, useMemo, useRef } from "react";
import { useRig } from "../lib/rig";
import { indexAt, pathOf, type P } from "../lib/track";
import type { TrackGeometry } from "../lib/types";
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
    const pts: P[] = [];
    ref.p.forEach((q, i) => {
      if (inRange(q, lo, hi)) pts.push([ref.x[i], ref.z[i]]);
    });
    return pathOf(pts);
  }, [ref, g, bucket]); // eslint-disable-line react-hooks/exhaustive-deps

  // Animation state lives in refs: the rAF loop writes straight to the SVG.
  const groupEl = useRef<SVGGElement>(null);
  const carEl = useRef<SVGPathElement>(null);
  const labelsEl = useRef<SVGGElement>(null);
  const anim = useRef({ x: 0, z: 0, vx: 0, vz: 0, at: 0, view: 0, viewTarget: 0, car: null as number | null, ahead: 150, aheadTarget: 150 });

  // Feed each telemetry sample into the animator.
  useEffect(() => {
    if (!live || !f?.world || !tl || !g) return;
    const a = anim.current;
    a.x = f.world[0];
    a.z = f.world[2];
    a.vx = f.velocity ? f.velocity[0] : 0;
    a.vz = f.velocity ? f.velocity[2] : 0;
    a.at = performance.now();
    a.viewTarget = tl.heading;
    a.car = tl.car_heading ?? null;
    const c = tl.corner;
    const toExit = c ? ((((c.exit - tl.p) % 1) + 1) % 1) * g.length_m : 0;
    const span = c ? (c.distance_m > 0 ? c.distance_m + 90 : toExit + 60) : 150;
    a.aheadTarget = Math.min(MAX_AHEAD, Math.max(MIN_AHEAD, span));
  }, [f, tl, live, g]);

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
      // Ease the view rotation and zoom so the picture never jumps.
      a.view += angDiff(a.viewTarget, a.view) * Math.min(1, dt * 6);
      a.ahead += (a.aheadTarget - a.ahead) * Math.min(1, dt * 3);
      const cx = w / 2;
      const cy = h * 0.8;
      const scale = h > 0 ? (cy - 24) / a.ahead : 1;
      const rot = -90 - a.view;
      groupEl.current?.setAttribute("transform", `translate(${cx},${cy}) rotate(${rot}) scale(${scale}) translate(${-x},${-z})`);
      const carRot = a.car === null ? 0 : a.car - a.view;
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
      {live && tl?.frac != null && <WidthGauge frac={tl.frac} />}
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
function WidthGauge({ frac }: { frac: number }) {
  const x = Math.max(-0.05, Math.min(1.05, frac));
  return (
    <div className="wgauge" aria-label="Position across the track">
      <span>L</span>
      <div className="wgauge__bar">
        <div className="wgauge__car" style={{ left: `${x * 100}%` }} />
      </div>
      <span>R</span>
    </div>
  );
}
