import { useMemo, useRef } from "react";
import { useRig } from "../lib/rig";
import { indexAt, pathOf, ribbonPath, type P } from "../lib/track";
import { Card, useSize } from "./common";

// The view zooms so the next corner (plus a bit of its exit) is always on
// screen: between MIN_AHEAD and MAX_AHEAD metres in front of the car.
const MIN_AHEAD = 90;
const MAX_AHEAD = 320;

/**
 * Heading-up close-up of the road ahead: real track edges, your best lap's
 * line, the braking point and where you are across the width.
 */
export function TurnByTurn() {
  const g = useRig((s) => s.track);
  const tl = useRig((s) => s.live.track);
  const f = useRig((s) => s.live.frame);
  const ref = useRig((s) => s.refTrace);
  const [box, { w, h }] = useSize<HTMLDivElement>();
  const ahead = useRef(150);

  // World-space paths are built once per track; only the transform moves.
  const paths = useMemo(() => {
    if (!g) return null;
    return {
      ribbon: ribbonPath(g),
      left: g.has_edges ? pathOf(g.left as P[], true) : "",
      right: g.has_edges ? pathOf(g.right as P[], true) : "",
      center: pathOf(g.center as P[], true),
    };
  }, [g]);
  const refPath = useMemo(() => {
    if (!ref?.x) return "";
    return pathOf(ref.x.map((x, i) => [x, ref.z[i]] as P));
  }, [ref]);

  if (!g || !paths) {
    return (
      <Card title="Road ahead" dim>
        <div className="upcoming">The close-up view appears once the track layout loads.</div>
      </Card>
    );
  }

  const live = !!tl && !!f?.world && f.status !== "off";
  const car: P = live ? [f!.world![0], f!.world![2]] : (g.center[0] as P);
  const heading = live ? tl!.heading : 0;
  const cx = w / 2;
  const cy = h * 0.8;
  const c0 = tl?.corner;
  const want = c0 ? Math.min(MAX_AHEAD, Math.max(MIN_AHEAD, c0.distance_m + 90)) : 150;
  ahead.current += (want - ahead.current) * 0.08; // ease, so zoom changes aren't jarring
  const scale = h > 0 ? (cy - 24) / ahead.current : 1;
  const rot = -90 - heading;
  const transform = `translate(${cx},${cy}) rotate(${rot}) scale(${scale}) translate(${-car[0]},${-car[1]})`;
  const rad = (rot * Math.PI) / 180;
  const project = (p: P): P => {
    const dx = (p[0] - car[0]) * scale;
    const dy = (p[1] - car[1]) * scale;
    return [cx + dx * Math.cos(rad) - dy * Math.sin(rad), cy + dx * Math.sin(rad) + dy * Math.cos(rad)];
  };

  const c = tl?.corner;
  // Braking point: a bar across the road at your best lap's brake point.
  let brake: [P, P] | null = null;
  if (c && c.brake_in_m !== null && g.has_edges && tl) {
    const i = indexAt(g, tl.p + c.brake_in_m / g.length_m);
    brake = [g.left[i] as P, g.right[i] as P];
  }
  const labels = live
    ? g.corners
        .map((k) => ({ k, ahead: (((k.apex - (tl?.p ?? 0)) % 1) + 1) % 1 }))
        .filter((o) => o.ahead * g.length_m < 320 && o.ahead > 0)
        .map((o) => ({ k: o.k, at: project(g.center[indexAt(g, o.k.apex)] as P) }))
    : [];

  return (
    <Card
      title={c ? c.label : "Road ahead"}
      right={live && tl?.frac != null ? <span className="pill">{sideText(tl.frac)}</span> : null}
    >
      <div ref={box} className="tbt">
        {w > 0 && (
          <svg width={w} height={h}>
            <g transform={transform}>
              <path d={paths.ribbon} className="tbt__road" fillRule="evenodd" />
              <path d={paths.left} className="tbt__edge" vectorEffect="non-scaling-stroke" />
              <path d={paths.right} className="tbt__edge" vectorEffect="non-scaling-stroke" />
              {!g.has_edges && <path d={paths.center} className="tbt__learnt" vectorEffect="non-scaling-stroke" />}
              {refPath && <path d={refPath} className="tbt__ref" vectorEffect="non-scaling-stroke" />}
              {brake && (
                <line
                  x1={brake[0][0]}
                  y1={brake[0][1]}
                  x2={brake[1][0]}
                  y2={brake[1][1]}
                  className="tbt__brake"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </g>
            {labels.map(({ k, at }) => (
              <text key={k.number} x={at[0]} y={at[1]} className="tbt__label" textAnchor="middle">
                {k.direction}
                {k.grade}
              </text>
            ))}
            {live && <path d={`M${cx},${cy - 16} L${cx + 10},${cy + 12} L${cx},${cy + 6} L${cx - 10},${cy + 12} Z`} className="tbt__car" />}
          </svg>
        )}
      </div>
      {live && tl?.frac != null && <WidthGauge frac={tl.frac} />}
    </Card>
  );
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
