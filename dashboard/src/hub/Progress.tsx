/**
 * Progress for one car + track: every clean lap over time, your personal best
 * as it came down, and how each session went (best, typical lap, consistency).
 */
import { useEffect, useMemo, useState } from "react";
import { delta, lapTime, prettyName } from "../lib/format";
import type { Combo } from "../lib/rig";
import { useSource } from "../lib/source";
import type { LapSummary } from "../lib/types";
import { useSize } from "../widgets/common";
import { SESSION_GAP_S, sessionsOf } from "./sessions";

const comboKey = (c: Combo) => `${c.game}|${c.car}|${c.track_key}`;

const day = (t: number) => new Date(t * 1000).toLocaleDateString("en-NZ", { day: "numeric", month: "short" });
const when = (t: number) =>
  new Date(t * 1000).toLocaleString("en-NZ", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export function Progress() {
  const src = useSource();
  const [combos, setCombos] = useState<Combo[]>([]);
  const [pick, setPick] = useState<string | null>(null);
  const [laps, setLaps] = useState<LapSummary[] | null>(null);
  useEffect(() => {
    src.combos().then(setCombos);
  }, [src]);
  const combo = combos.find((c) => comboKey(c) === pick) ?? combos[0] ?? null;
  useEffect(() => {
    if (!combo) return;
    let ok = true;
    setLaps(null);
    src.laps(combo).then((x) => ok && setLaps(x));
    return () => {
      ok = false;
    };
  }, [src, combo && comboKey(combo)]); // eslint-disable-line react-hooks/exhaustive-deps

  const sessions = useMemo(() => (laps ? sessionsOf(laps) : []), [laps]);
  const valid = useMemo(() => (laps ?? []).filter((l) => l.valid).sort((a, b) => a.started_at - b.started_at), [laps]);
  const pb = valid.length ? valid.reduce((a, b) => (b.lap_time_ms < a.lap_time_ms ? b : a)) : null;

  if (!combos.length) return <div className="card"><div className="upcoming">No laps uploaded yet.</div></div>;
  return (
    <div className="card prog">
      <div className="card__head">
        <span className="card__title">Progress</span>
        <select className="lapsel combosel" value={combo ? comboKey(combo) : ""} onChange={(e) => setPick(e.target.value)} aria-label="Car and track">
          {combos.map((c) => (
            <option key={comboKey(c)} value={comboKey(c)}>
              {prettyName(c.car)} · {prettyName(c.track_key)} ({c.valid_laps ?? 0})
            </option>
          ))}
        </select>
      </div>
      {!laps ? (
        <div className="upcoming">Loading…</div>
      ) : !pb ? (
        <div className="upcoming">No clean laps on this car + track yet.</div>
      ) : (
        <div className="prog__body">
          <div className="prog__tiles">
            <Tile label="Personal best" value={lapTime(pb.lap_time_ms)} sub={`lap ${pb.lap_number} · ${day(pb.started_at)}`} best />
            <Tile label="Improved by" value={sessions.length > 1 ? delta((pb.lap_time_ms - sessions[0].best) / 1000, 3).replace("−", "") + " s" : "–"} sub={sessions.length > 1 ? `since your first session (${lapTime(sessions[0].best)})` : "drive another session"} />
            <Tile label="Clean laps" value={String(valid.length)} sub={`of ${laps.length} driven`} />
            <Tile label="Sessions" value={String(sessions.length)} sub={`since ${day(sessions[0].start)}`} />
          </div>
          <LapChart valid={valid} pbId={pb.id} />
          <table className="prog__table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Clean laps</th>
                <th>Best</th>
                <th>Typical lap</th>
                <th title="How much your clean laps vary (standard deviation)">Consistency</th>
              </tr>
            </thead>
            <tbody>
              {[...sessions].reverse().map((s) => (
                <tr key={s.start}>
                  <td>{when(s.start)}</td>
                  <td>{s.laps.length} <span className="muted">/ {s.all}</span></td>
                  <td className={s.best === pb.lap_time_ms ? "prog__pb" : ""}>{lapTime(s.best)}</td>
                  <td>{lapTime(Math.round(s.median))}</td>
                  <td>{s.laps.length > 1 ? `± ${(s.spread / 1000).toFixed(2)} s` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, sub, best }: { label: string; value: string; sub: string; best?: boolean }) {
  return (
    <div className="prog__tile">
      <div className="prog__label">{label}</div>
      <div className={`prog__value ${best ? "prog__pb" : ""}`}>{value}</div>
      <div className="prog__sub">{sub}</div>
    </div>
  );
}

const PAD = { l: 64, r: 16, t: 14, b: 28 };

/** Every clean lap (dots) and your personal best as it came down (stepped line). */
function LapChart({ valid, pbId }: { valid: LapSummary[]; pbId: number }) {
  const [box, { w }] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<LapSummary | null>(null);
  const h = 260;
  const pb = Math.min(...valid.map((l) => l.lap_time_ms));
  // Keep the scale on the laps that matter: slower than PB + 8 % sits on the top edge.
  const cap = pb * 1.08;
  const ys = valid.map((l) => Math.min(l.lap_time_ms, cap));
  const lo = pb - (Math.max(...ys) - pb) * 0.06 - 200;
  const hi = Math.max(...ys) + 200;
  // x: lap order (sessions far apart in time would otherwise squash), session breaks marked
  const n = valid.length;
  const sx = (i: number) => PAD.l + (n === 1 ? 0.5 : i / (n - 1)) * (w - PAD.l - PAD.r);
  const sy = (ms: number) => PAD.t + (1 - (Math.min(ms, cap) - lo) / (hi - lo)) * (h - PAD.t - PAD.b);
  let best = Infinity;
  const steps: string[] = [];
  valid.forEach((l, i) => {
    if (l.lap_time_ms < best) {
      if (best !== Infinity) steps.push(`L${sx(i).toFixed(1)},${sy(best).toFixed(1)}`);
      best = l.lap_time_ms;
      steps.push(`${steps.length ? "L" : "M"}${sx(i).toFixed(1)},${sy(best).toFixed(1)}`);
    }
  });
  steps.push(`L${sx(n - 1).toFixed(1)},${sy(best).toFixed(1)}`);
  const breaks = valid.map((l, i) => (i > 0 && l.started_at - valid[i - 1].started_at > SESSION_GAP_S ? i : -1)).filter((i) => i > 0);
  // Round ticks: 0.25 / 0.5 / 1 / 2 / 5 s apart, about four of them.
  const stepMs = [250, 500, 1000, 2000, 5000, 10000].find((st) => (hi - lo) / st <= 5) ?? 20000;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / stepMs) * stepMs; t <= hi; t += stepMs) ticks.push(t);
  // Session date labels under each stretch of the chart.
  const starts = [0, ...breaks];
  const labels = starts.map((i, k) => ({ x: (sx(i) + sx((starts[k + 1] ?? n) - 1)) / 2, text: day(valid[i].started_at) }));
  const pick = (e: React.MouseEvent<SVGSVGElement>) => {
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left;
    let k = 0;
    valid.forEach((_, i) => {
      if (Math.abs(sx(i) - x) < Math.abs(sx(k) - x)) k = i;
    });
    setHover(valid[k]);
  };
  return (
    <div className="prog__chart">
      <div className="cd__legend">
        <span><i className="prog__dot" />clean lap</span>
        <span><i className="prog__line" />personal best so far</span>
        <span className="muted">dashed lines: a new session</span>
      </div>
      <div ref={box} style={{ height: h, position: "relative" }}>
        {w > 0 && (
          <svg width={w} height={h} onMouseMove={pick} onMouseLeave={() => setHover(null)}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.l} x2={w - PAD.r} y1={sy(t)} y2={sy(t)} className="strip__grid" />
                <text x={PAD.l - 8} y={sy(t)} className="strip__tick" textAnchor="end" dy="0.35em">{lapTime(Math.round(t)).replace(/0+$/, "").replace(/\.$/, "")}</text>
              </g>
            ))}
            {breaks.map((i) => (
              <line key={i} x1={(sx(i) + sx(i - 1)) / 2} x2={(sx(i) + sx(i - 1)) / 2} y1={PAD.t} y2={h - PAD.b} className="strip__apex" />
            ))}
            {labels.map((l) => (
              <text key={l.text + l.x} x={l.x} y={h - 8} className="strip__tick" textAnchor="middle">{l.text}</text>
            ))}
            <path d={steps.join("")} className="prog__pbline" />
            {valid.map((l, i) => (
              <circle
                key={l.id}
                cx={sx(i)}
                cy={sy(l.lap_time_ms)}
                r={hover?.id === l.id ? 6 : l.id === pbId ? 5 : 3.5}
                className={l.id === pbId ? "prog__pbdot" : "prog__lapdot"}
              />
            ))}
            {hover && (
              <line x1={sx(valid.indexOf(hover))} x2={sx(valid.indexOf(hover))} y1={PAD.t} y2={h - PAD.b} className="strip__cross" />
            )}
          </svg>
        )}
        {hover && (
          <div className="prog__tip" style={{ left: Math.min(Math.max(sx(valid.indexOf(hover)) + 10, 0), Math.max(0, w - 190)) }}>
            <b>{lapTime(hover.lap_time_ms)}</b>
            <span>
              lap {hover.lap_number} · {when(hover.started_at)}
            </span>
            {hover.lap_time_ms > pb && <span className="muted">{delta((hover.lap_time_ms - pb) / 1000, 3)} on your best</span>}
          </div>
        )}
      </div>
    </div>
  );
}
