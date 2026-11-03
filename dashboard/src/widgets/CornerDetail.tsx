import { useMemo, useState } from "react";
import { delta } from "../lib/format";
import { fitTrack, type Pt } from "../lib/geometry";
import { profile, timeDelta, type Profile, type Trace } from "../lib/profile";
import { startDrill } from "../lib/rig";
import { GRADE_COLORS, type P } from "../lib/track";
import type { CornerLap, Mastery, PracticeSection, TrackGeometry } from "../lib/types";
import { useSize } from "./common";

// Validated as a pair against the card colour (colour-blind safe, enough contrast).
export const YOU = "#f2522e";
export const OTHER = "#a970f5";

type Corner = TrackGeometry["corners"][number];

interface Props {
  g: TrackGeometry;
  corner: Corner;
  mine: CornerLap;
  other: CornerLap | null;
  otherLabel: string | null;
  myTrace: Trace | null;
  otherTrace: Trace | null;
  mastery: Mastery | undefined;
  section: PracticeSection | undefined;
  onStep: (dir: 1 | -1) => void;
}

/** Everything about one corner on this lap, side by side with the comparison lap. */
export function CornerDetail({ g, corner: c, mine, other, otherLabel, myTrace, otherTrace, mastery, section, onStep }: Props) {
  const L = g.length_m;
  const exitM = ((((c.exit - c.apex) % 1) + 1) % 1) * L;
  const brakeBack = Math.max(mine.brake_m ?? 0, other?.brake_m ?? 0);
  const from = -Math.min(320, Math.max(90, brakeBack + 60));
  const to = Math.min(320, exitM + 90);
  const me = useMemo(() => profile(myTrace, c.apex, L, from, to), [myTrace, c.apex, L, from, to]);
  const them = useMemo(() => profile(otherTrace, c.apex, L, from, to), [otherTrace, c.apex, L, from, to]);
  const dt = useMemo(() => (me && them ? timeDelta(me, them) : null), [me, them]);
  const [hover, setHover] = useState<number | null>(null);
  const label = otherLabel ?? "the other lap";
  const vs = mine.vs_s;

  return (
    <div className="cd">
      <div className="cd__head">
        <button className="btn btn--sm btn--ghost" onClick={() => onStep(-1)} aria-label="Previous corner">‹</button>
        <div className="cd__title">
          <span className="cd__grade" title={`${c.direction === "L" ? "Left" : "Right"}, severity ${c.grade} (1 = tightest)`}>
            {c.direction}
            {c.grade}
          </span>
          <span className="cd__name">
            {c.number}. {c.label}
          </span>
        </div>
        <button className="btn btn--sm btn--ghost" onClick={() => onStep(1)} aria-label="Next corner">›</button>
      </div>

      <div className="cd__verdict">
        <div>
          <div className="cd__big">{mine.time_s.toFixed(2)}s</div>
          <div className="muted">through the corner</div>
        </div>
        {vs !== undefined && (
          <div>
            <div className={`cd__big ${vs <= 0.02 ? "good" : vs <= 0.1 ? "amber" : "bad"}`}>{delta(vs)}</div>
            <div className="muted">vs {label}</div>
          </div>
        )}
        {mastery && (
          <div>
            <div className="cd__big">
              <span className="mdot" style={{ background: GRADE_COLORS[mastery.grade] }} /> {mastery.best_s.toFixed(2)}s
            </div>
            <div className="muted">
              best ever here
              {mastery.spread_s != null ? ` · ±${mastery.spread_s.toFixed(2)}s over ${Math.min(mastery.laps, 10)} laps` : ""}
            </div>
          </div>
        )}
        {section && (
          <button className="btn btn--sm cd__drill" onClick={() => startDrill({ section: section.number })}>
            Practise {section.name}
          </button>
        )}
      </div>

      {(mine.notes?.length || mine.advice?.length) ? (
        <div className="cd__notes">
          {mine.notes && mine.notes.length > 0 && (
            <>
              <div className="cd__sub">What was different</div>
              <ul>
                {mine.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </>
          )}
          {mine.advice && mine.advice.length > 0 && (
            <>
              <div className="cd__sub">Using the track</div>
              <ul>
                {mine.advice.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : null}

      <div className="cd__legend">
        <span><Key c={YOU} />You (this lap)</span>
        {them && <span><Key c={OTHER} dash />{cap(label)}</span>}
        <span className="muted">● braking starts · numbers = slowest speed</span>
      </div>

      <CloseUp g={g} corner={c} me={me} them={them} mine={mine} other={other} hover={hover} from={from} to={to} />

      <Readout me={me} them={them} dt={dt} hover={hover} label={label} />
      <div className="cd__charts" onMouseLeave={() => setHover(null)}>
        <Strip title="Speed (km/h)" x={me?.x ?? []} series={[me && { v: me.speed, c: YOU }, them && { v: them.speed, c: OTHER, dash: true }]} hover={hover} setHover={setHover} height={120} />
        <Strip title="Brake (%)" x={me?.x ?? []} series={[me && { v: me.brake.map((b) => b * 100), c: YOU }, them && { v: them.brake.map((b) => b * 100), c: OTHER, dash: true }]} hover={hover} setHover={setHover} height={64} fixed={[0, 100]} />
        <Strip title="Throttle (%)" x={me?.x ?? []} series={[me && { v: me.gas.map((b) => b * 100), c: YOU }, them && { v: them.gas.map((b) => b * 100), c: OTHER, dash: true }]} hover={hover} setHover={setHover} height={64} fixed={[0, 100]} />
        {dt && (
          <Strip title={`Time vs ${label} (s) — above the line = losing`} x={me?.x ?? []} series={[{ v: dt, c: "var(--text)" }]} hover={hover} setHover={setHover} height={80} zero axisX />
        )}
        {!dt && <AxisNote x={me?.x ?? []} />}
      </div>

      <Table mine={mine} other={other} label={label} />
    </div>
  );
}

/** Line sample for legends: solid for you, dashed for the other lap (not colour alone). */
function Key({ c, dash }: { c: string; dash?: boolean }) {
  return (
    <svg width="18" height="8" className="key" aria-hidden>
      <line x1="1" x2="17" y1="4" y2="4" stroke={c} strokeWidth="3" strokeLinecap="round" strokeDasharray={dash ? "4 3" : undefined} />
    </svg>
  );
}

function cap(s: string): string {
  return s[0].toUpperCase() + s.slice(1);
}

// -- close-up of the corner on the real track ---------------------------------

function CloseUp(props: {
  g: TrackGeometry;
  corner: Corner;
  me: Profile | null;
  them: Profile | null;
  mine: CornerLap;
  other: CornerLap | null;
  hover: number | null;
  from: number;
  to: number;
}) {
  const { g, corner: c, me, them, mine, other, hover, from, to } = props;
  const [box, { w, h }] = useSize<HTMLDivElement>();
  const L = g.length_m;
  const idx = useMemo(() => {
    const out: number[] = [];
    const n = g.center.length;
    for (let i = 0; i < n; i++) {
      let rel = g.progress[i] - c.apex;
      rel -= Math.round(rel);
      const x = rel * L;
      if (x >= from - 30 && x <= to + 30) out.push(i);
    }
    // keep them in driving order across the line
    return out.sort((a, b) => {
      const ra = g.progress[a] - c.apex - Math.round(g.progress[a] - c.apex);
      const rb = g.progress[b] - c.apex - Math.round(g.progress[b] - c.apex);
      return ra - rb;
    });
  }, [g, c.apex, L, from, to]);
  const fit = useMemo(() => fitTrack(idx.map((i) => g.center[i] as Pt), w, h, 28), [g, idx, w, h]);
  const pr = (p: P) => fit.project(p[0], p[1]);
  const path = (pts: P[]) => pts.map((p, i) => `${i ? "L" : "M"}${pr(p)[0].toFixed(1)},${pr(p)[1].toFixed(1)}`).join("");
  const line = (pf: Profile) => path(pf.wx.map((x, i) => [x, pf.wz[i]] as P));
  const at = (pf: Profile, x: number): P | null => {
    if (x < pf.x[0] || x > pf.x[pf.x.length - 1]) return null;
    const i = Math.round((x - pf.x[0]) / (pf.x[1] - pf.x[0]));
    return pr([pf.wx[i], pf.wz[i]]);
  };
  // Slowest point within this corner only (the window also shows bits of its neighbours).
  const entryM = -((((c.apex - c.entry) % 1) + 1) % 1) * L;
  const exitM = ((((c.exit - c.apex) % 1) + 1) % 1) * L;
  const slow = (pf: Profile) => {
    let k = -1;
    pf.speed.forEach((v, i) => {
      if (pf.x[i] >= entryM && pf.x[i] <= exitM && (k < 0 || v < pf.speed[k])) k = i;
    });
    return Math.max(0, k);
  };

  const road = g.has_edges
    ? `${path(idx.map((i) => g.left[i] as P))}${idx
        .map((i) => g.right[i] as P)
        .reverse()
        .map((p) => `L${pr(p)[0].toFixed(1)},${pr(p)[1].toFixed(1)}`)
        .join("")}Z`
    : "";
  // "apex" label just inside the corner, off the racing lines.
  const ai = idx.reduce((b, i) => (Math.abs(g.progress[i] - c.apex) < Math.abs(g.progress[b] - c.apex) ? i : b), idx[0] ?? 0);
  const mid = pr(g.center[ai] as P);
  const inner = pr((g.has_edges ? (c.direction === "L" ? g.left[ai] : g.right[ai]) : g.center[ai]) as P);
  const dx = inner[0] - mid[0];
  const dy = inner[1] - mid[1];
  const dl = Math.hypot(dx, dy) || 1;
  const apexPt: P = [inner[0] + (dx / dl) * 22, inner[1] + (dy / dl) * 22];

  return (
    <div ref={box} className="cd__map">
      {w > 0 && idx.length > 1 && (
        <svg width={w} height={h}>
          {road && <path d={road} className="cd__road" />}
          {g.has_edges && (
            <>
              <path d={path(idx.map((i) => g.left[i] as P))} className="cd__edge" />
              <path d={path(idx.map((i) => g.right[i] as P))} className="cd__edge" />
            </>
          )}
          {!g.has_edges && <path d={path(idx.map((i) => g.center[i] as P))} className="cd__edge" />}
          <text x={apexPt[0]} y={apexPt[1]} className="cd__apex" textAnchor="middle" dy="0.35em">apex</text>
          {me && <path d={line(me)} className="cd__line" stroke={YOU} />}
          {/* dashed on top, so both show where the lines overlap */}
          {them && <path d={line(them)} className="cd__line cd__line--other" stroke={OTHER} />}
          {them && other?.brake_m != null && <Dot at={at(them, -other.brake_m)} colour={OTHER} hollow />}
          {me && mine.brake_m != null && <Dot at={at(me, -mine.brake_m)} colour={YOU} />}
          {them && <SpeedTag at={at(them, them.x[slow(them)])} text={Math.round(them.speed[slow(them)])} colour={OTHER} flip />}
          {me && <SpeedTag at={at(me, me.x[slow(me)])} text={Math.round(me.speed[slow(me)])} colour={YOU} />}
          {hover !== null && me && <Dot at={at(me, hover)} colour="var(--text)" small />}
          {hover !== null && them && <Dot at={at(them, hover)} colour={OTHER} small hollow />}
          <Arrow g={g} idx={idx} pr={pr} />
        </svg>
      )}
      {!me && <div className="map__empty">Loading the lap…</div>}
    </div>
  );
}

function Dot({ at, colour, hollow, small }: { at: P | null; colour: string; hollow?: boolean; small?: boolean }) {
  if (!at) return null;
  return (
    <circle cx={at[0]} cy={at[1]} r={small ? 5 : 7} fill={hollow ? "var(--card)" : colour} stroke={hollow ? colour : "var(--card)"} strokeWidth={hollow ? 2.5 : 2} />
  );
}

function SpeedTag({ at, text, colour, flip }: { at: P | null; text: number; colour: string; flip?: boolean }) {
  if (!at) return null;
  // yours above-right, the other lap's below-left, so they never sit on each other
  return (
    <g transform={`translate(${at[0]},${at[1]})`}>
      <circle r={4} fill={colour} stroke="var(--card)" strokeWidth={2} />
      <text className="cd__tag" x={flip ? -8 : 8} y={flip ? 18 : -8} textAnchor={flip ? "end" : "start"}>{text}</text>
    </g>
  );
}

/** Small arrow on the track showing which way you drive. */
function Arrow({ g, idx, pr }: { g: TrackGeometry; idx: number[]; pr: (p: P) => P }) {
  if (idx.length < 8) return null;
  const a = pr(g.center[idx[2]] as P);
  const b = pr(g.center[idx[6]] as P);
  const ang = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
  return (
    <g transform={`translate(${a[0]},${a[1]}) rotate(${ang})`} className="cd__dir">
      <path d="M-8,-6 L4,0 L-8,6" />
    </g>
  );
}

// -- charts ---------------------------------------------------------------------

interface Series {
  v: number[];
  c: string;
  dash?: boolean;
}

const PAD_L = 40;
const PAD_R = 8;

function Strip(props: {
  title: string;
  x: number[];
  series: (Series | null | false)[];
  hover: number | null;
  setHover: (x: number | null) => void;
  height: number;
  fixed?: [number, number];
  zero?: boolean;
  axisX?: boolean;
}) {
  const { title, x, hover, setHover, height, fixed, zero, axisX } = props;
  const series = props.series.filter(Boolean) as Series[];
  const [box, { w }] = useSize<HTMLDivElement>();
  if (!x.length || !series.length) return null;
  const all = series.flatMap((s) => s.v);
  let lo = fixed ? fixed[0] : Math.min(...all);
  let hi = fixed ? fixed[1] : Math.max(...all);
  if (zero) {
    const m = Math.max(0.05, Math.abs(lo), Math.abs(hi));
    lo = -m;
    hi = m;
  } else if (!fixed) {
    const pad = (hi - lo) * 0.08 || 5;
    lo -= pad;
    hi += pad;
  }
  const h = height;
  const top = 4;
  const bottom = axisX ? 18 : 4;
  const sx = (v: number) => PAD_L + ((v - x[0]) / (x[x.length - 1] - x[0])) * (w - PAD_L - PAD_R);
  const sy = (v: number) => top + (1 - (v - lo) / (hi - lo)) * (h - top - bottom);
  const path = (v: number[]) => v.map((y, i) => `${i ? "L" : "M"}${sx(x[i]).toFixed(1)},${sy(y).toFixed(1)}`).join("");
  const fmt = (v: number) => (zero ? v.toFixed(2) : Math.round(v).toString());
  const ticks = zero ? [lo, 0, hi] : [lo + (hi - lo) * 0.1, hi - (hi - lo) * 0.1];
  const span = x[x.length - 1] - x[0];
  const every = (w - PAD_L - PAD_R) / span * 50 >= 60 ? 50 : 100;
  const xticks = x.filter((v) => Math.round(v) % every === 0);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    if (px < PAD_L) return setHover(null);
    const v = x[0] + ((px - PAD_L) / (w - PAD_L - PAD_R)) * (x[x.length - 1] - x[0]);
    setHover(Math.round(v / 2) * 2);
  };
  return (
    <div className="strip">
      <div className="strip__title">{title}</div>
      <div ref={box} style={{ height: h }}>
        {w > 0 && (
          <svg width={w} height={h} onMouseMove={onMove}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD_L} x2={w - PAD_R} y1={sy(t)} y2={sy(t)} className={zero && t === 0 ? "strip__zero" : "strip__grid"} />
                <text x={PAD_L - 6} y={sy(t)} className="strip__tick" textAnchor="end" dy="0.35em">{fmt(t)}</text>
              </g>
            ))}
            <line x1={sx(0)} x2={sx(0)} y1={top} y2={h - bottom} className="strip__apex" />
            {zero && (
              <>
                <path d={`${path(series[0].v)}L${sx(x[x.length - 1])},${sy(0)}L${sx(x[0])},${sy(0)}Z`} className="strip__area" />
              </>
            )}
            {series.map((s, i) => (
              <path key={i} d={path(s.v)} stroke={s.c} className={`strip__line ${s.dash ? "strip__line--dash" : ""}`} />
            ))}
            {axisX &&
              xticks.map((v) => (
                <text key={v} x={sx(v)} y={h - 4} className="strip__tick" textAnchor="middle">
                  {v === 0 ? "apex" : `${v > 0 ? "+" : ""}${v} m`}
                </text>
              ))}
            {hover !== null && hover >= x[0] && hover <= x[x.length - 1] && (
              <line x1={sx(hover)} x2={sx(hover)} y1={0} y2={h} className="strip__cross" />
            )}
          </svg>
        )}
      </div>
    </div>
  );
}

function AxisNote({ x }: { x: number[] }) {
  if (!x.length) return null;
  return <div className="muted strip__note">Distance runs left to right; the faint line is the apex. Hover the charts to read values.</div>;
}

function Readout({ me, them, dt, hover, label }: { me: Profile | null; them: Profile | null; dt: number[] | null; hover: number | null; label: string }) {
  if (!me) return null;
  if (hover === null) return <div className="cd__readout muted">Hover the charts to compare the two laps at any point.</div>;
  const i = Math.max(0, Math.min(me.x.length - 1, Math.round((hover - me.x[0]) / (me.x[1] - me.x[0]))));
  const where = hover === 0 ? "at the apex" : `${Math.abs(hover)} m ${hover < 0 ? "before" : "after"} the apex`;
  const row = (p: Profile) =>
    `${Math.round(p.speed[i])} km/h · gear ${p.gear[i] || "–"} · brake ${Math.round(p.brake[i] * 100)}% · throttle ${Math.round(p.gas[i] * 100)}%`;
  return (
    <div className="cd__readout">
      <b>{where}</b>
      <span><Key c={YOU} />You: {row(me)}</span>
      {them && <span><Key c={OTHER} dash />{cap(label)}: {row(them)}</span>}
      {dt && <span>{dt[i] > 0 ? `${dt[i].toFixed(2)} s down so far` : `${(-dt[i]).toFixed(2)} s up so far`}</span>}
    </div>
  );
}

// -- numbers side by side ---------------------------------------------------------

function Table({ mine, other, label }: { mine: CornerLap; other: CornerLap | null; label: string }) {
  type Row = { name: string; a: string; b: string; diff: string; tone: "good" | "bad" | "" };
  const rows: Row[] = [];
  const num = (v: number | null | undefined, unit: string, d = 0) => (v == null ? "–" : `${v.toFixed(d)}${unit}`);
  const cmp = (name: string, a: number | null | undefined, b: number | null | undefined, unit: string, better: "high" | "low" | null, words: [string, string], d = 0, min = 0.5) => {
    let diff = "";
    let tone: Row["tone"] = "";
    if (a != null && b != null && Math.abs(a - b) >= min) {
      const up = a > b;
      diff = `${Math.abs(a - b).toFixed(d)}${unit} ${up ? words[0] : words[1]}`;
      if (better) tone = (better === "high") === up ? "good" : "bad";
    }
    rows.push({ name, a: num(a, unit, d), b: other ? num(b, unit, d) : "", diff, tone });
  };
  cmp("Time through the corner", mine.time_s, other?.time_s, " s", "low", ["slower", "quicker"], 2, 0.01);
  cmp("Braking starts", mine.brake_m, other?.brake_m, " m", null, ["earlier", "later"], 0, 3);
  cmp("Speed when braking starts", mine.entry_kmh, other?.entry_kmh, " km/h", "high", ["faster", "slower"], 0, 1);
  cmp("Hardest braking", mine.peak_brake != null ? mine.peak_brake * 100 : null, other?.peak_brake != null ? other.peak_brake * 100 : null, " %", null, ["harder", "softer"], 0, 3);
  cmp("Slowest point", mine.min_speed_kmh, other?.min_speed_kmh, " km/h", "high", ["faster", "slower"], 0, 1);
  cmp("Gear at the apex", mine.apex_gear, other?.apex_gear, "", null, ["higher", "lower"], 0, 1);
  cmp("Full throttle again", mine.throttle_m, other?.throttle_m, " m", "low", ["later", "sooner"], 0, 3);
  cmp("Speed at the exit", mine.exit_kmh, other?.exit_kmh, " km/h", "high", ["faster", "slower"], 0, 1);
  cmp("Coasting (no pedals)", mine.coast_s, other?.coast_s, " s", "low", ["more", "less"], 1, 0.1);
  return (
    <table className="cd__table">
      <thead>
        <tr>
          <th />
          <th><Key c={YOU} />You</th>
          {other && <th><Key c={OTHER} dash />{cap(label)}</th>}
          {other && <th>Difference</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>{r.name}{r.name === "Braking starts" ? <small> before apex</small> : r.name === "Full throttle again" ? <small> after apex</small> : null}</td>
            <td>{r.a}</td>
            {other && <td>{r.b}</td>}
            {other && <td className={r.tone}>{r.diff}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
