import { useEffect, useMemo, useState } from "react";
import { delta, lapTime } from "../lib/format";
import { fitTrack, type Pt } from "../lib/geometry";
import { fetchCorners, fetchTrace, startDrill, useRig } from "../lib/rig";
import { GRADE_COLORS, indexAt, pathOf, type P } from "../lib/track";
import type { CornerLap, CornerReport, TrackGeometry } from "../lib/types";
import { Card, useSize } from "./common";

type Mode = "phase" | "speed" | "delta" | "grade";
const MODES: [Mode, string][] = [
  ["phase", "Brake / coast / throttle"],
  ["speed", "Speed"],
  ["delta", "Gain / loss"],
  ["grade", "Corner grades"],
];
type Trace = Record<string, number[]>;

/** Post-session view: your line coloured four ways, plus every corner broken down. */
export function LapAnalysis({ wide = false }: { wide?: boolean } = {}) {
  const g = useRig((s) => s.track);
  const latest = useRig((s) => s.corners);
  const laps = useRig((s) => s.laps);
  const ref = useRig((s) => s.refTrace);
  const [mode, setMode] = useState<Mode>("phase");
  const [lapId, setLapId] = useState<number | null>(null);
  const [report, setReport] = useState<CornerReport | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [focus, setFocus] = useState<number | null>(null);

  const shownId = lapId ?? latest?.lap_id ?? null;
  useEffect(() => {
    if (shownId === null) return;
    let live = true;
    fetchCorners(shownId).then((r) => live && setReport(r));
    fetchTrace(shownId, 10).then((t) => live && setTrace(t));
    return () => {
      live = false;
    };
  }, [shownId, latest]);

  if (!g) {
    return (
      <Card title="Lap analysis" dim>
        <div className="upcoming">Analysis appears once the track layout loads and you've done a lap.</div>
      </Card>
    );
  }
  const valid = laps.filter((l) => l.valid);
  const rows = report?.lap ?? [];
  const renderCorner = (c: TrackGeometry["corners"][number], i: number) => {
            const r = rows[i];
            if (!r) return null;
            const m = report?.mastery.find((x) => x.corner === c.number);
            return (
              <div
                key={c.number}
                className={`crow ${focus === c.number ? "crow--focus" : ""}`}
                onMouseEnter={() => setFocus(c.number)}
                onMouseLeave={() => setFocus(null)}
              >
                <div className="crow__head">
                  <span className="mdot" style={{ background: GRADE_COLORS[m?.grade ?? "new"] }} />
                  <span className="crow__name">
                    {c.number}. {c.label}
                  </span>
                  <span className="crow__time">{r.time_s.toFixed(2)}s</span>
                  <span className={`crow__loss ${lossClass(r.loss_s)}`}>{r.loss_s != null ? delta(r.loss_s) : ""}</span>
                </div>
                <div className="crow__stats">
                  <span>min {Math.round(r.min_speed_kmh)} km/h</span>
                  <span>gear {r.apex_gear}</span>
                  {r.coast_s > 0.2 && <span className="warn">coast {r.coast_s.toFixed(1)}s</span>}
                  {m && m.spread_s !== null && <span>± {m.spread_s.toFixed(2)}s over {Math.min(m.laps, 10)} laps</span>}
                </div>
                {r.entry_frac !== undefined && <WidthUse c={c.direction} r={r} />}
                {r.advice && r.advice.length > 0 && (
                  <ul className="crow__advice">
                    {r.advice.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          
  };
  return (
    <Card
      title="Lap analysis"
      right={
        <select className="lapsel" value={shownId ?? ""} onChange={(e) => setLapId(Number(e.target.value) || null)}>
          {valid.map((l) => (
            <option key={l.id} value={l.id}>
              Lap {l.lap_number} · {lapTime(l.lap_time_ms)}
              {l.id === report?.reference_lap_id ? " (best)" : ""}
            </option>
          ))}
        </select>
      }
    >
      <div className={`la ${wide ? "la--wide" : ""}`}>
        <div className="la__left">
        <div className="la__modes" role="tablist">
          {MODES.map(([m, label]) => (
            <button key={m} className={`chipbtn ${mode === m ? "chipbtn--on" : ""}`} onClick={() => setMode(m)}>
              {label}
            </button>
          ))}
        </div>
        <ColouredMap g={g} trace={trace} ref_={ref} mode={mode} rows={rows} focus={focus} onPick={setFocus} />
        <Legend mode={mode} />
        </div>
        <div className="la__list">
          {report?.chapters && report.chapters.length > 0 && (
            <div className="chapters">
              <div className="chapters__title">Chapters</div>
              {report.chapters.map((ch) => {
                const d = ch.time_s != null && ch.ref_s != null ? ch.time_s - ch.ref_s : null;
                return (
                  <div key={ch.number} className="chap">
                    <div className="chap__head">
                      <span className="chap__num">{ch.number}</span>
                      <span className="chap__name">{ch.name}</span>
                      <span className="crow__time">{ch.time_s != null ? `${ch.time_s.toFixed(1)}s` : ""}</span>
                      <span className={`crow__loss ${lossClass(d)}`}>{d !== null ? delta(d) : ""}</span>
                      <button className="btn btn--sm btn--ghost" onClick={() => startDrill({ chapter: ch.number })}>
                        Practise
                      </button>
                    </div>
                    {ch.summary && <div className="chap__sum">{ch.summary}</div>}
                  </div>
                );
              })}
              <div className="chapters__title">Sections</div>
            </div>
          )}
          <div className="wkey">
            <b>How to read the strips:</b> each corner has a bar from the <b>L</b>eft edge of the track to the{" "}
            <b>R</b>ight edge. <span className="wkey__m">E</span> = where you turned in,{" "}
            <span className="wkey__m">A</span> = apex, <span className="wkey__m">X</span> = exit. The green end is the
            inside of the corner — a classic line goes outside → inside → outside.
          </div>
          {(report?.practice?.length ? report.practice : g.practice).map((ps) => {
            const d = ps.time_s != null && ps.ref_s != null ? ps.time_s - ps.ref_s : null;
            return (
              <div key={`s${ps.number}`} className="psec">
                <div className="psec__head">
                  <span className="psec__name">{ps.name}</span>
                  <span className="crow__time">{ps.time_s != null ? `${ps.time_s.toFixed(2)}s` : ""}</span>
                  <span className={`crow__loss ${lossClass(d)}`} title="vs your best lap">
                    {d !== null ? delta(d) : ""}
                  </span>
                  <button className="btn btn--sm" onClick={() => startDrill({ section: ps.number })}>
                    Practise
                  </button>
                </div>
                {ps.drill_best_s ? <div className="psec__sub">best drill run {ps.drill_best_s.toFixed(2)}s</div> : null}
                {ps.corners.map((num) => {
                  const i = g.corners.findIndex((k) => k.number === num);
                  return i >= 0 ? renderCorner(g.corners[i], i) : null;
                })}
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function lossClass(loss: number | null | undefined): string {
  if (loss == null) return "";
  return loss <= 0.05 ? "good" : loss <= 0.2 ? "amber" : "bad";
}

function gradeColour(loss: number | null | undefined): string {
  if (loss == null) return "#59616d";
  return loss <= 0.05 ? "#3ddc84" : loss <= 0.2 ? "#ffc542" : "#ff5252";
}

/** Entry, apex and exit marked on a strip that runs from the left edge to the right edge. */
function WidthUse({ c, r }: { c: "L" | "R"; r: CornerLap }) {
  const marks: [string, number | undefined][] = [
    ["E", r.entry_frac],
    ["A", r.apex_frac],
    ["X", r.exit_frac],
  ];
  const title: Record<string, string> = { E: "turn-in", A: "apex", X: "exit" };
  return (
    <div className="wuse" title="Where you were across the track: E = turn-in, A = apex, X = exit">
      <span className="wuse__side">L</span>
      <div className="wuse__bar">
        <div className={`wuse__inside wuse__inside--${c}`} />
        {marks.map(([k, f]) =>
          f === undefined ? null : (
            <span key={k} className="wuse__mark" title={title[k]} style={{ left: `${Math.max(0, Math.min(1, f)) * 100}%` }}>
              {k}
            </span>
          ),
        )}
      </div>
      <span className="wuse__side">R</span>
    </div>
  );
}

function Legend({ mode }: { mode: Mode }) {
  const items: Record<Mode, [string, string][]> = {
    phase: [
      ["#ff5252", "braking"],
      ["#8b94a1", "coasting"],
      ["#3ddc84", "throttle"],
    ],
    speed: [
      ["hsl(220 80% 60%)", "slow"],
      ["hsl(60 80% 55%)", ""],
      ["hsl(0 80% 60%)", "fast"],
    ],
    delta: [
      ["#3ddc84", "gaining on best"],
      ["#8b94a1", "even"],
      ["#ff5252", "losing"],
    ],
    grade: [
      ["#3ddc84", "≤0.05s lost"],
      ["#ffc542", "≤0.2s"],
      ["#ff5252", "more"],
    ],
  };
  return (
    <div className="legend">
      {items[mode].map(([c, l], i) => (
        <span key={i}>
          <i style={{ background: c }} />
          {l}
        </span>
      ))}
    </div>
  );
}

function ColouredMap(props: {
  g: TrackGeometry;
  trace: Trace | null;
  ref_: Trace | null;
  mode: Mode;
  rows: CornerLap[];
  focus: number | null;
  onPick: (n: number | null) => void;
}) {
  const { g, trace, ref_, mode, rows, focus } = props;
  const [box, { w, h }] = useSize<HTMLDivElement>();
  const fit = useMemo(() => fitTrack(g.center as Pt[], w, h, 18), [g, w, h]);
  const proj = (p: P): P => fit.project(p[0], p[1]);
  const road = useMemo(
    () => (g.has_edges ? `${pathOf(g.left.map((p) => proj(p as P)), true)}${pathOf(g.right.map((p) => proj(p as P)), true)}` : ""),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [g, fit],
  );
  const segments = useMemo(() => (trace ? colourSegments(trace, ref_, mode, g, rows) : []), [trace, ref_, mode, g, rows]);

  return (
    <div ref={box} className="la__map">
      {w > 0 && (
        <svg width={w} height={h}>
          {road && <path d={road} className="map__road" fillRule="evenodd" />}
          {segments.map(([colour, pts], i) => (
            <path key={i} d={pathOf(pts.map(proj))} stroke={colour} className="la__seg" />
          ))}
          {g.corners.map((c) => {
            const at = proj(g.center[indexAt(g, c.apex)] as P);
            return (
              <g
                key={c.number}
                transform={`translate(${at[0]},${at[1]})`}
                onMouseEnter={() => props.onPick(c.number)}
                onMouseLeave={() => props.onPick(null)}
                className="la__cnum"
              >
                <circle r={focus === c.number ? 14 : 10} className="map__cnum" />
                <text className="map__cnum-text" textAnchor="middle" dy="0.35em">
                  {c.number}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {!trace && <div className="map__empty">Loading lap…</div>}
    </div>
  );
}

/** Split the lap into runs of one colour: [colour, points][]. */
function colourSegments(tr: Trace, ref: Trace | null, mode: Mode, g: TrackGeometry, rows: CornerLap[]): [string, P[]][] {
  const n = tr.x?.length ?? 0;
  if (n < 2) return [];
  const smin = Math.min(...tr.speed);
  const smax = Math.max(...tr.speed);
  const refTime = ref ? timeLookup(ref) : null;
  const d = refTime ? tr.p.map((p, i) => tr.t[i] - refTime(p)) : null;

  const colourAt = (i: number): string => {
    switch (mode) {
      case "phase":
        return tr.brake[i] > 0.1 ? "#ff5252" : tr.gas[i] > 0.1 ? "#3ddc84" : "#8b94a1";
      case "speed": {
        const k = (tr.speed[i] - smin) / Math.max(1, smax - smin);
        return `hsl(${Math.round(220 - 220 * k)} 80% 58%)`;
      }
      case "delta": {
        if (!d) return "#8b94a1";
        const j = Math.min(n - 1, i + 15); // ~1.5 s ahead at 10 Hz
        const rate = d[j] - d[i];
        return rate < -0.03 ? "#3ddc84" : rate > 0.03 ? "#ff5252" : "#8b94a1";
      }
      case "grade": {
        const p = tr.p[i];
        const k = g.corners.findIndex((c) => c.entry <= p && p <= c.exit);
        return k >= 0 ? gradeColour(rows[k]?.loss_s) : "#3a4049";
      }
    }
  };

  const out: [string, P[]][] = [];
  let cur: [string, P[]] | undefined;
  for (let i = 0; i < n; i++) {
    if (tr.t[i] < 5 && tr.p[i] > 0.9) continue; // pre-line samples
    const c = colourAt(i);
    const pt: P = [tr.x[i], tr.z[i]];
    if (!cur || cur[0] !== c) {
      const prev: P | undefined = cur ? cur[1][cur[1].length - 1] : undefined;
      cur = [c, prev ? [prev, pt] : [pt]];
      out.push(cur);
    } else cur[1].push(pt);
  }
  return out;
}

function timeLookup(tr: Trace): (p: number) => number {
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
