import { useMemo, useRef } from "react";
import { prettyName } from "../lib/format";
import { fitTrack, toPath, type Pt } from "../lib/geometry";
import { useRig } from "../lib/rig";
import { GRADE_COLORS, indexAt, pathOf, slice, type P } from "../lib/track";
import { Card, useSize } from "./common";

/**
 * The whole track, north-up. Uses the game's layout (real width, named corners)
 * when available; otherwise your best lap, or a trail drawn as you drive.
 */
export function TrackMap() {
  const g = useRig((s) => s.track);
  const outline = useRig((s) => s.outline);
  const markers = useRig((s) => s.markers);
  const session = useRig((s) => s.session);
  const frame = useRig((s) => s.live.frame);
  const drill = useRig((s) => s.live.track?.drill ?? null);
  const mastery = useRig((s) => s.corners?.mastery);
  const [ref, { w, h }] = useSize<HTMLDivElement>();

  // Breadcrumbs for tracks we know nothing about yet.
  const crumbs = useRef<{ key: string; pts: Pt[] }>({ key: "", pts: [] });
  const key = session?.track_key ?? "";
  if (crumbs.current.key !== key) crumbs.current = { key, pts: [] };
  if (!g && outline.length === 0 && frame?.world && frame.status === "live") {
    const p: Pt = [frame.world[0], frame.world[2]];
    const last = crumbs.current.pts.at(-1);
    if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 4) crumbs.current.pts.push(p);
  }

  const base: Pt[] = useMemo(() => {
    if (g) return g.center as Pt[];
    if (outline.length) return outline.map((p) => [p[0], p[1]] as Pt);
    return crumbs.current.pts.slice();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [g, outline, Math.floor(crumbs.current.pts.length / 25)]);
  const fit = useMemo(() => fitTrack(base, w, h, 22), [base, w, h]);
  const proj = (p: P): P => fit.project(p[0], p[1]);

  const drawn = useMemo(() => {
    if (g?.has_edges) {
      return {
        road: `${pathOf(g.left.map((p) => proj(p as P)), true)}${pathOf(g.right.map((p) => proj(p as P)), true)}`,
        line: "",
      };
    }
    return { road: "", line: toPath(base.map(([x, z]) => fit.project(x, z)), base.length > 50) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [g, base, fit]);

  const car = frame?.world ? fit.project(frame.world[0], frame.world[2]) : null;
  const gradeOf = (n: number) => mastery?.find((m) => m.corner === n)?.grade;

  return (
    <Card
      title={prettyName(session?.track_key) || "Track"}
      right={g ? (g.source === "laps" ? <span className="pill">learnt from your laps</span> : null) : <span className="pill">learning layout</span>}
    >
      <div ref={ref} className="map">
        {w > 0 && (
          <svg width={w} height={h} role="img" aria-label="Track map">
            {drawn.road ? (
              <path d={drawn.road} className="map__road" fillRule="evenodd" />
            ) : (
              <>
                <path d={drawn.line} className="map__track-shadow" />
                <path d={drawn.line} className="map__track" />
              </>
            )}
            {g && drill && (
              <path d={pathOf(slice(g, drill.start_p, drill.end_p).map(proj))} className="map__drill" />
            )}
            {g?.corners.map((c) => {
              const at = proj(g.center[indexAt(g, c.apex)] as P);
              const grade = gradeOf(c.number);
              return (
                <g key={c.number} transform={`translate(${at[0]},${at[1]})`}>
                  <circle r={11} className="map__cnum" style={grade && grade !== "new" ? { stroke: GRADE_COLORS[grade] } : undefined} />
                  <text className="map__cnum-text" textAnchor="middle" dy="0.35em">
                    {c.number}
                  </text>
                </g>
              );
            })}
            {markers.map((m) =>
              m.x !== null && m.z !== null ? (
                <g key={m.id} transform={`translate(${fit.project(m.x, m.z).join(",")})`}>
                  <rect x={-5} y={-5} width={10} height={10} className="map__marker" transform="rotate(45)" />
                </g>
              ) : null,
            )}
            {car && <circle cx={car[0]} cy={car[1]} r={9} className="map__car" />}
          </svg>
        )}
        {base.length < 2 && <div className="map__empty">Drive a lap to draw the map</div>}
      </div>
    </Card>
  );
}
