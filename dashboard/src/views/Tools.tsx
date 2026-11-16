/** Hardware checks from your laps, out of the way: force feedback clipping
 * (TS-PC) and how you use the brake pedal (T-LCM). */
import { useEffect, useState } from "react";
import { prettyName } from "../lib/format";
import { saveConfig, useRig } from "../lib/rig";
import type { Advice } from "../lib/types";

interface Ffb {
  laps: number;
  clipping_pct: number;
  peak: number;
  worst_corners: string[];
  gain_change_pct: number;
  advice: string;
}
interface Pedals {
  stops: number;
  peak_median: number;
  peak_spread: number;
  full_pct: number;
  release_s_median: number;
  abrupt_pct: number;
  notes: string[];
}
interface ToolsReport {
  car: string | null;
  track_key: string | null;
  ffb: Ffb | null;
  pedals: Pedals | null;
}

export function Tools() {
  const [r, setR] = useState<ToolsReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [adv, setAdv] = useState<Advice | null>(null);
  const loadAdvice = () =>
    fetch("/api/advice")
      .then((x) => x.json())
      .then(setAdv)
      .catch(() => undefined);
  useEffect(() => {
    fetch("/api/tools")
      .then((x) => x.json())
      .then(setR)
      .catch(() => setErr("Can't reach Pitwall."));
    loadAdvice();
  }, []);
  return (
    <div className="settings tools">
      <header className="settings__head">
        <a href="#/settings" className="settings__back">
          ← Settings
        </a>
        <h1>Tools</h1>
        <span className="muted">{r?.car ? `${prettyName(r.car)} · ${prettyName(r.track_key ?? "")}, last 10 clean laps` : ""}</span>
      </header>
      {err && <p className="warn">{err}</p>}
      {!r ? (
        !err && <p className="muted">Working it out…</p>
      ) : (
        <div className="tools__grid">
          <CarSetup adv={adv} onSaved={loadAdvice} />
          <section className="settings__card">
            <h2>Force feedback (TS-PC)</h2>
            {r.ffb ? (
              <>
                <div className="tools__big">
                  {r.ffb.clipping_pct}% <span className="muted">of the time clipping</span>
                </div>
                <p>{r.ffb.advice}</p>
                {r.ffb.worst_corners.length > 0 && <p className="muted">Mostly at: {r.ffb.worst_corners.join(", ")}.</p>}
                <p className="field__hint">
                  Clipping means the wheel is already at full force, so you can't feel what the tyres are doing there. Change
                  the gain for this car in Content Manager (or AC's controls), then drive a few laps and check again.
                </p>
              </>
            ) : (
              <p className="muted">Drive a few clean laps on the current version to measure it.</p>
            )}
          </section>
          <section className="settings__card">
            <h2>Brake pedal (T-LCM)</h2>
            {r.pedals ? (
              <>
                <div className="tools__big">
                  {Math.round(r.pedals.peak_median * 100)}% <span className="muted">typical peak · {r.pedals.full_pct}% of stops at full</span>
                </div>
                <ul>
                  {r.pedals.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
                <p className="muted">
                  {r.pedals.stops} stops · peaks vary ±{Math.round(r.pedals.peak_spread * 100)}% · release takes {r.pedals.release_s_median}s
                  {r.pedals.abrupt_pct ? ` · ${r.pedals.abrupt_pct}% sudden releases` : ""}
                </p>
              </>
            ) : (
              <p className="muted">Needs a few laps with braking to say anything.</p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

const WHEEL = ["Front left", "Front right", "Rear left", "Rear right"];

/** Brake bias, ABS, TC and tyre pressures: what your recent laps on the current settings say. */
function CarSetup({ adv, onSaved }: { adv: Advice | null; onSaved: () => void }) {
  const config = useRig((s) => s.config);
  const car = adv?.car;
  const saved = car ? config?.advisor?.target_psi?.[car] : undefined;
  const [front, setFront] = useState("");
  const [rear, setRear] = useState("");
  useEffect(() => {
    setFront(saved ? String(saved[0]) : "");
    setRear(saved ? String(saved[1]) : "");
  }, [car, saved?.[0], saved?.[1]]);
  const save = async () => {
    if (!car || !config) return;
    const f = parseFloat(front);
    const r = parseFloat(rear);
    const all = { ...(config.advisor?.target_psi ?? {}) };
    if (f > 5 && r > 5) all[car] = [f, r];
    else delete all[car];
    await saveConfig({ ...config, advisor: { target_psi: all } });
    onSaved();
  };
  const s = adv?.settings;
  const now = [
    s?.bb != null && `brake bias ${(s.bb * 100).toFixed(1)}% front`,
    s?.abs != null && (s.abs ? `ABS ${s.abs}` : "ABS off"),
    s?.tc != null && (s.tc ? `TC ${s.tc}` : "TC off"),
  ].filter(Boolean);
  return (
    <section className="settings__card tools__setup">
      <h2>Car setup: brake bias, ABS, TC, tyre pressures</h2>
      {!adv || adv.laps === 0 ? (
        <p className="muted">Drive a few laps to get suggestions. They come from lock-ups, wheelspin and hot tyre pressures.</p>
      ) : (
        <>
          <p className="muted">
            From your last {adv.laps} lap{adv.laps === 1 ? "" : "s"} on the current settings{now.length ? ` (${now.join(", ")})` : ""}.
            Change one and it starts again.
          </p>
          {adv.advice.length === 0 ? (
            <div className="tools__big">
              Nothing to change <span className="muted">{adv.laps < 3 ? "yet: needs 3 laps" : "no lock-ups, wheelspin or uneven pressures"}</span>
            </div>
          ) : (
            <ul className="tools__advice">
              {adv.advice.map((a) => (
                <li key={a.key}>
                  <b>{a.do}</b>
                  <div>{a.title}.</div>
                  <div className="muted">{a.why}</div>
                </li>
              ))}
            </ul>
          )}
          {adv.psi && (
            <div className="tools__psi" aria-label="Hot tyre pressures">
              {adv.psi.map((p, i) => (
                <div key={WHEEL[i]}>
                  <span className="muted">{WHEEL[i]}</span>
                  <b>{p.toFixed(1)}</b> psi hot
                </div>
              ))}
            </div>
          )}
          <div className="tools__target">
            <label>
              This car's ideal hot pressure, front
              <input inputMode="decimal" value={front} placeholder={adv.target_psi ? String(adv.target_psi[0]) : "psi"} onChange={(e) => setFront(e.target.value)} onBlur={save} />
            </label>
            <label>
              rear
              <input inputMode="decimal" value={rear} placeholder={adv.target_psi ? String(adv.target_psi[1]) : "psi"} onChange={(e) => setRear(e.target.value)} onBlur={save} />
            </label>
          </div>
          <p className="field__hint">
            {adv.target_psi
              ? "Pressure advice is against these. "
              : "Optional. Without it, pressure advice only evens out left and right. Content Manager shows the ideal in the setup's tyre tab. "}
            Pitwall only suggests: you change the setting in the car or the pits.
          </p>
        </>
      )}
    </section>
  );
}
