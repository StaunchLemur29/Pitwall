import { useEffect, useMemo, useState } from "react";
import { delta, lapTime } from "../lib/format";
import { fitTrack, type Pt } from "../lib/geometry";
import { timeLookup, type Trace } from "../lib/profile";
import { prettyName } from "../lib/format";
import { fetchCombos, fetchCorners, fetchGeometry, fetchLaps, fetchTrace, rig, startDrill, useRig, type Combo } from "../lib/rig";
import { GRADE_COLORS, indexAt, pathOf, type P } from "../lib/track";
import type { CornerLap, CornerReport, LapSummary, TrackGeometry } from "../lib/types";
import { CornerDetail } from "./CornerDetail";
import { Card, useSize } from "./common";

type Mode = "phase" | "speed" | "delta" | "grade" | "systems";
const MODES: [Mode, string][] = [
  ["delta", "Gain / loss"],
  ["phase", "Brake / coast / throttle"],
  ["speed", "Speed"],
  ["grade", "Corners vs your best"],
];

/** Post-session view: a lap summary, your line on the map, and any corner in detail against another lap. */
const comboKey = (c: Combo | null) => (c ? `${c.game}|${c.car}|${c.track_key}` : "live");

export function LapAnalysis({
  wide = false,
  onShowing,
}: { wide?: boolean; onShowing?: (c: { car: string; track_key: string } | null) => void } = {}) {
  const liveG = useRig((s) => s.track);
  const latest = useRig((s) => s.corners);
  const liveLaps = useRig((s) => s.laps);
  const liveTheo = useRig((s) => s.live.theoretical_best_ms);
  // Which car + track: the one you're driving, or any you've driven before.
  const [combos, setCombos] = useState<Combo[]>([]);
  const [combo, setCombo] = useState<Combo | null>(null);
  const [comboG, setComboG] = useState<TrackGeometry | null>(null);
  const [comboLaps, setComboLaps] = useState<LapSummary[]>([]);
  useEffect(() => {
    fetchCombos().then(setCombos);
  }, [liveLaps.length, liveG]);
  const active = combo ?? (!liveG && combos[0] ? combos[0] : null);
  const activeKey = comboKey(active);
  useEffect(() => {
    if (!active) return;
    let ok = true;
    setComboG(null);
    fetchGeometry(active).then((x) => ok && setComboG(x));
    fetchLaps(active).then((x) => ok && setComboLaps(x));
    return () => {
      ok = false;
    };
  }, [activeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const g = active ? comboG : liveG;
  const laps = active ? comboLaps : liveLaps;
  const [mode, setMode] = useState<Mode>("delta");
  const [lapId, setLapId] = useState<number | null>(null);
  const [compareId, setCompareId] = useState<number | null>(null);
  const [report, setReport] = useState<CornerReport | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [otherTrace, setOtherTrace] = useState<Trace | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [picked, setPicked] = useState<number | null>(null);

  const requested = lapId ?? (active ? null : latest?.lap_id ?? null);
  useEffect(() => {
    if (requested === null && !active) return;
    let live = true;
    fetchCorners(requested, compareId, active).then((r) => live && setReport(r));
    return () => {
      live = false;
    };
  }, [requested, compareId, activeKey, latest]); // eslint-disable-line react-hooks/exhaustive-deps
  const shownId = report?.lap_id ?? requested;
  useEffect(() => {
    if (shownId === null) return;
    let live = true;
    fetchTrace(shownId, 30).then((t) => live && setTrace(t));
    return () => {
      live = false;
    };
  }, [shownId]);
  const theo = active ? report?.theoretical_best_ms ?? null : liveTheo;
  useEffect(() => {
    onShowing?.(report?.car && report.track_key ? { car: report.car, track_key: report.track_key } : null);
  }, [report?.car, report?.track_key]); // eslint-disable-line react-hooks/exhaustive-deps
  const canDrill = !active; // drills run on the car + track you're driving
  const pickCombo = (key: string) => {
    const c = combos.find((x) => comboKey(x) === key) ?? null;
    setCombo(c && !c.live ? c : null);
    setLapId(null);
    setCompareId(null);
    setPicked(null);
    setReport(null);
    setTrace(null);
  };
  const comboPicker =
    combos.length > 1 || active ? (
      <select className="lapsel combosel" value={activeKey === "live" ? comboKey(combos.find((c) => c.live) ?? null) : activeKey} onChange={(e) => pickCombo(e.target.value)} aria-label="Car and track">
        {!combos.some((c) => c.live) && liveG && <option value="live">Now driving</option>}
        {combos.map((c) => (
          <option key={comboKey(c)} value={comboKey(c)}>
            {c.live ? "● " : ""}
            {prettyName(c.car)} · {prettyName(c.track_key)} ({c.valid_laps ?? 0})
          </option>
        ))}
      </select>
    ) : null;
  const otherId = report?.compare_lap_id ?? null;
  useEffect(() => {
    if (otherId === null) return setOtherTrace(null);
    let live = true;
    fetchTrace(otherId, 30).then((t) => live && setOtherTrace(t));
    return () => {
      live = false;
    };
  }, [otherId]);

  const rows = report?.lap ?? [];
  // Biggest losses first: where the time went.
  const losses = useMemo(
    () =>
      rows
        .map((r, i) => ({ r, c: g?.corners[i] }))
        .filter((x) => x.c && (x.r.vs_s ?? 0) > 0.03)
        .sort((a, b) => (b.r.vs_s ?? 0) - (a.r.vs_s ?? 0))
        .slice(0, 3),
    [rows, g],
  );

  if (!g) {
    return (
      <Card title="Lap analysis" dim right={comboPicker}>
        <div className="upcoming">
          {active ? "Loading that track…" : "Analysis appears once the track layout loads and you've done a lap."}
        </div>
      </Card>
    );
  }
  const valid = laps.filter((l) => l.valid);
  const shown = laps.find((l) => l.id === shownId);
  const other = laps.find((l) => l.id === otherId);
  const label = report?.compare_label ?? null;
  const ci = Math.max(0, g.corners.findIndex((k) => k.number === (picked ?? losses[0]?.c?.number ?? g.corners[0]?.number)));
  const corner = g.corners[ci];
  const mine = rows[ci];
  const otherRow = report?.compare?.find((x) => x.corner === corner?.number) ?? null;
  const section = (report?.practice?.length ? report.practice : g.practice).find((ps) => ps.corners.includes(corner?.number));
  const step = (d: 1 | -1) => setPicked(g.corners[(ci + d + g.corners.length) % g.corners.length].number);
  const lapDelta = shown && other ? (shown.lap_time_ms - other.lap_time_ms) / 1000 : null;

  const summary = (
    <div className="lsum">
      <div className="lsum__stat">
        <div className="lsum__big">{lapTime(shown?.lap_time_ms)}</div>
        <div className="muted">lap {shown?.lap_number ?? ""}</div>
      </div>
      {lapDelta !== null && (
        <div className="lsum__stat">
          <div className={`lsum__big ${lapDelta <= 0 ? "good" : "bad"}`}>{delta(lapDelta, 3)}</div>
          <div className="muted">vs {label}</div>
        </div>
      )}
      {theo ? (
        <div className="lsum__stat">
          <div className="lsum__big lsum__theo">{lapTime(theo)}</div>
          <div className="muted">best sectors combined</div>
        </div>
      ) : null}
      <div className="lsum__where">
        <div className="cd__sub">{losses.length ? "Where the time went" : rows.length && other ? "No corner lost more than 0.03 s" : "Drive another clean lap to compare"}</div>
        {losses.map(({ r, c }) => (
          <button key={c!.number} className={`lossbtn ${corner?.number === c!.number ? "lossbtn--on" : ""}`} onClick={() => setPicked(c!.number)}>
            <span className="lossbtn__name">{c!.label}</span>
            <span className="bad">{delta(r.vs_s)}</span>
            <span className="lossbtn__why">{r.notes?.[0] ?? "Small losses all the way through rather than one mistake."}</span>
          </button>
        ))}
      </div>
    </div>
  );

  const chip = (num: number, why = false) => {
    const i = g.corners.findIndex((k) => k.number === num);
    if (i < 0) return null;
    const r = rows[i];
    const m = report?.mastery.find((x) => x.corner === num);
    const open = !wide && corner?.number === num;
    const notes = r ? (r.notes?.length ? r.notes : r.advice ?? []) : [];
    return (
      <div key={`${why ? "w" : "c"}${num}`} className={`cwrap ${open ? "cwrap--open" : ""}`}>
        <button
          className={`cchip ${corner?.number === num ? "cchip--on" : ""} ${focus === num ? "cchip--hover" : ""}`}
          onClick={() => setPicked(num)}
          onMouseEnter={() => setFocus(num)}
          onMouseLeave={() => setFocus(null)}
        >
          <span className="mdot" style={{ background: GRADE_COLORS[m?.grade ?? "new"] }} />
          <span className="cchip__name">{num}. {g.corners[i].label}</span>
          {r && <span className="cchip__t">{r.time_s.toFixed(2)}s</span>}
          {r?.vs_s !== undefined && <span className={`cchip__d ${vsClass(r.vs_s)}`}>{delta(r.vs_s)}</span>}
        </button>
        {why && !open && <div className="cwrap__why">{notes[0] ?? "Small losses all the way through rather than one mistake."}</div>}
        {open && (
          <div className="cwrap__body">
            {notes.slice(0, 2).map((n) => (
              <div key={n} className="cwrap__note">{n}</div>
            ))}
            <div className="cwrap__actions">
              {section && canDrill && (
                <button className="btn btn--sm" onClick={() => startDrill({ section: section.number })}>
                  Practise {section.name}
                </button>
              )}
              <button className="btn btn--sm btn--ghost" onClick={() => rig.action("open_analysis")}>
                Full breakdown ↗
              </button>
            </div>
          </div>
        )}
      </div>
    );
  };

  const hasSystems = !!(report?.systems?.drs || report?.systems?.battery);
  const modeList: [Mode, string][] = hasSystems ? [...MODES, ["systems", "Battery & DRS"]] : MODES;
  const modes = (
    <div className="la__modes" role="tablist">
      {modeList.map(([m, l]) => (
        <button key={m} className={`chipbtn ${mode === m ? "chipbtn--on" : ""}`} onClick={() => setMode(m)}>
          {l}
        </button>
      ))}
    </div>
  );

  const systemNotes = report?.systems?.notes ?? [];
  const systemsBlock =
    report && (systemNotes.length > 0 || report.car_systems?.length) ? (
      <div className="sysnotes">
        <div className="chapters__title">Car systems</div>
        {report.car_systems?.length ? <div className="sysnotes__car">{report.car_systems.join(" · ")}</div> : null}
        {systemNotes.map((n) => (
          <div key={n} className="sysnotes__note">{n}</div>
        ))}
      </div>
    ) : null;

  const list = (
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
                  <span className={`crow__loss ${vsClass(d)}`} title="vs your best lap">{d !== null ? delta(d) : ""}</span>
                  {canDrill && (
                    <button className="btn btn--sm btn--ghost" onClick={() => startDrill({ chapter: ch.number })}>
                      Practise
                    </button>
                  )}
                </div>
                {ch.summary && <div className="chap__sum">{ch.summary}</div>}
              </div>
            );
          })}
        </div>
      )}
      {!wide && losses.length > 0 && (
        <>
          <div className="chapters__title">Where the time went</div>
          {losses.map(({ c }) => chip(c!.number, true))}
        </>
      )}
      {!wide && systemsBlock}
      <div className="chapters__title">Sections{wide ? " · click a corner for the detail" : ""}</div>
      {(report?.practice?.length ? report.practice : g.practice).map((ps) => {
        const d = ps.time_s != null && ps.ref_s != null ? ps.time_s - ps.ref_s : null;
        return (
          <div key={`s${ps.number}`} className="psec">
            <div className="psec__head">
              <span className="psec__name">{ps.name}</span>
              <span className="crow__time">{ps.time_s != null ? `${ps.time_s.toFixed(2)}s` : ""}</span>
              <span className={`crow__loss ${vsClass(d)}`} title="vs your best lap">
                {d !== null ? delta(d) : ""}
              </span>
              {canDrill && (
                <button className="btn btn--sm" onClick={() => startDrill({ section: ps.number })}>
                  Practise
                </button>
              )}
            </div>
            {ps.drill_best_s ? <div className="psec__sub">best drill run {ps.drill_best_s.toFixed(2)}s</div> : null}
            <div className="psec__corners">{ps.corners.map((num) => chip(num))}</div>
          </div>
        );
      })}
    </div>
  );

  const lapPicker = (
    <select className="lapsel" value={shownId ?? ""} onChange={(e) => setLapId(Number(e.target.value) || null)} aria-label="Lap to analyse">
      {valid.map((l) => (
        <option key={l.id} value={l.id}>
          Lap {l.lap_number} · {lapTime(l.lap_time_ms)}
          {l.id === report?.reference_lap_id ? " (best)" : ""}
        </option>
      ))}
    </select>
  );
  const pickers = (
        <span className="lapsels">
          {comboPicker}
          {lapPicker}
          <span className="muted">vs</span>
          <select className="lapsel" value={compareId ?? ""} onChange={(e) => setCompareId(Number(e.target.value) || null)} aria-label="Compare with">
            <option value="">{compareId === null && label ? `auto: ${label}` : "auto"}</option>
            {valid
              .filter((l) => l.id !== shownId)
              .map((l) => (
                <option key={l.id} value={l.id}>
                  Lap {l.lap_number} · {lapTime(l.lap_time_ms)}
                  {l.id === report?.reference_lap_id ? " (best)" : ""}
                </option>
              ))}
          </select>
        </span>
  );

  return (
    <Card title="Lap analysis" right={wide ? pickers : lapPicker}>
      {!wide && comboPicker && <div className="la__combo">{comboPicker}</div>}
      {wide ? (
        <div className="la la--wide">
          <div className="la__left">
            {summary}
            {systemsBlock}
            {modes}
            <ColouredMap g={g} trace={trace} ref_={otherTrace} mode={mode} rows={rows} focus={focus ?? corner?.number ?? null} onPick={setFocus} onSelect={setPicked} />
            <Legend mode={mode} label={label} />
            {list}
          </div>
          <div className="la__right">
            {corner && mine ? (
              <CornerDetail
                g={g}
                corner={corner}
                mine={mine}
                other={otherRow}
                otherLabel={label}
                myTrace={trace}
                otherTrace={otherTrace}
                mastery={report?.mastery.find((x) => x.corner === corner.number)}
                section={canDrill ? section : undefined}
                onStep={step}
              />
            ) : (
              <div className="upcoming">Drive a clean lap and it'll be broken down here, corner by corner.</div>
            )}
          </div>
        </div>
      ) : (
        <div className="la la--narrow">
          <div className="nsum">
            <span className="nsum__t">{lapTime(shown?.lap_time_ms)}</span>
            {lapDelta !== null && <span className={lapDelta <= 0 ? "good" : "bad"}>{delta(lapDelta, 3)}</span>}
            {lapDelta !== null && <span className="muted">vs {label}</span>}
            {theo ? <span className="nsum__theo" title="best sectors combined">optimal {lapTime(theo)}</span> : null}
          </div>
          {modes}
          <ColouredMap g={g} trace={trace} ref_={otherTrace} mode={mode} rows={rows} focus={focus ?? corner?.number ?? null} onPick={setFocus} onSelect={setPicked} />
          <Legend mode={mode} label={label} />
          {list}
        </div>
      )}
    </Card>
  );
}

/** Gap to the comparison lap: green only when you were quicker, grey when it's a wash. */
function vsClass(v: number | null | undefined): string {
  if (v == null) return "";
  return v < -0.02 ? "good" : v <= 0.02 ? "even" : v <= 0.1 ? "amber" : "bad";
}

function gradeColour(loss: number | null | undefined): string {
  if (loss == null) return "#59616d";
  return loss <= 0.05 ? "#3ddc84" : loss <= 0.2 ? "#ffc542" : "#ff5252";
}

function Legend({ mode, label }: { mode: Mode; label: string | null }) {
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
      ["#3ddc84", `gaining on ${label ?? "the other lap"}`],
      ["#8b94a1", "even"],
      ["#ff5252", "losing"],
    ],
    systems: [
      ["#3ddc84", "DRS open"],
      ["#ff5252", "battery empty on the power"],
      ["hsl(212 70% 60%)", "battery (darker = lower)"],
    ],
    grade: [
      ["#3ddc84", "within 0.05 s of your best ever"],
      ["#ffc542", "within 0.2 s"],
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
  onSelect: (n: number) => void;
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
                onClick={() => props.onSelect(c.number)}
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
        const j = Math.min(n - 1, i + 45); // ~1.5 s ahead at 30 Hz
        const rate = d[j] - d[i];
        return rate < -0.03 ? "#3ddc84" : rate > 0.03 ? "#ff5252" : "#8b94a1";
      }
      case "systems": {
        // DRS open in green, an empty battery while on the power in red,
        // otherwise blue that's darker the lower the battery.
        if ((tr.drs?.[i] ?? 0) >= 2) return "#3ddc84";
        const b = tr.batt?.[i] ?? 0;
        if (b <= 0.02 && tr.gas[i] >= 0.9) return "#ff5252";
        return `hsl(212 70% ${Math.round(22 + 46 * b)}%)`;
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
