/** Hardware checks from your laps, out of the way: force feedback clipping
 * (TS-PC) and how you use the brake pedal (T-LCM). */
import { useEffect, useState } from "react";
import { prettyName } from "../lib/format";

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
  useEffect(() => {
    fetch("/api/tools")
      .then((x) => x.json())
      .then(setR)
      .catch(() => setErr("Can't reach Pitwall."));
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
