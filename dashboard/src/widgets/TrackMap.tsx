import { useMemo, useRef } from "react";
import { prettyName } from "../lib/format";
import { fitTrack, toPath, type Pt } from "../lib/geometry";
import { useRig } from "../lib/rig";
import { Card, useSize } from "./common";

/**
 * Track outline from your best stored lap (or, on a brand-new track, a
 * breadcrumb trail drawn as you drive), with the car and any marked spots.
 */
export function TrackMap() {
  const outline = useRig((s) => s.outline);
  const markers = useRig((s) => s.markers);
  const session = useRig((s) => s.session);
  const frame = useRig((s) => s.live.frame);
  const [ref, { w, h }] = useSize<HTMLDivElement>();

  // Breadcrumbs for tracks we have no lap for yet.
  const crumbs = useRef<{ key: string; pts: Pt[] }>({ key: "", pts: [] });
  const key = session?.track_key ?? "";
  if (crumbs.current.key !== key) crumbs.current = { key, pts: [] };
  if (outline.length === 0 && frame?.world && frame.status === "live") {
    const p: Pt = [frame.world[0], frame.world[2]];
    const last = crumbs.current.pts.at(-1);
    if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 4) crumbs.current.pts.push(p);
  }

  const pts: Pt[] = useMemo(
    () => (outline.length ? outline.map((p) => [p[0], p[1]] as Pt) : crumbs.current.pts.slice()),
    // crumbs grow every frame; refit the breadcrumb view every ~25 points
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [outline, Math.floor(crumbs.current.pts.length / 25)],
  );
  const fit = useMemo(() => fitTrack(pts, w, h, 18), [pts, w, h]);
  const path = useMemo(() => toPath(pts.map(([x, z]) => fit.project(x, z)), outline.length > 0), [pts, fit, outline.length]);
  const startPt = pts.length ? fit.project(pts[0][0], pts[0][1]) : null;
  const car = frame?.world ? fit.project(frame.world[0], frame.world[2]) : null;

  return (
    <Card title={prettyName(session?.track_key) || "Track"} right={outline.length ? null : <span className="pill">learning layout</span>}>
      <div ref={ref} className="map">
        {w > 0 && (
          <svg width={w} height={h} role="img" aria-label="Track map">
            <path d={path} className="map__track-shadow" />
            <path d={path} className="map__track" />
            {startPt && <circle cx={startPt[0]} cy={startPt[1]} r={5} className="map__start" />}
            {markers.map((m) =>
              m.x !== null && m.z !== null ? (
                <g key={m.id} transform={`translate(${fit.project(m.x, m.z).join(",")})`}>
                  <rect x={-5} y={-5} width={10} height={10} className="map__marker" transform="rotate(45)" />
                </g>
              ) : null,
            )}
            {car && <circle cx={car[0]} cy={car[1]} r={10} className="map__car" />}
          </svg>
        )}
        {pts.length < 2 && <div className="map__empty">Drive a lap to draw the map</div>}
      </div>
    </Card>
  );
}
