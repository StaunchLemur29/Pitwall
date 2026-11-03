import { useEffect, useRef, useState } from "react";
import { lag } from "../lib/rig";

/**
 * Press L to toggle. Shows where delay comes from:
 * game → rig (game Hz), rig loop (rig Hz), rig → screen (data age, gaps), screen (fps).
 */
export function LagMeter() {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem("pitwall.lag") === "1";
    } catch {
      return false;
    }
  });
  const [, force] = useState(0);
  const fps = useRef({ n: 0, t0: performance.now(), value: 0, worst: 0, last: performance.now() });

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "l" && !(e.target instanceof HTMLInputElement)) {
        setOn((v) => {
          try {
            localStorage.setItem("pitwall.lag", v ? "0" : "1");
          } catch {
            /* ignore */
          }
          return !v;
        });
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  useEffect(() => {
    if (!on) return;
    let raf = 0;
    const loop = (now: number) => {
      const f = fps.current;
      f.worst = Math.max(f.worst, now - f.last);
      f.last = now;
      f.n++;
      if (now - f.t0 >= 1000) {
        f.value = (f.n * 1000) / (now - f.t0);
        f.n = 0;
        f.t0 = now;
        force((x) => x + 1);
        f.worst = 0;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [on]);

  if (!on) return null;
  const s = lag.summary();
  const bad = (v: number, warn: number, badAt: number) => (v >= badAt ? "bad" : v >= warn ? "amber" : "good");
  const low = (v: number, warn: number, badAt: number) => (v <= badAt ? "bad" : v <= warn ? "amber" : "good");
  return (
    <div className="lagm" title="Press L to hide">
      <div className="lagm__title">Lag meter (L to hide)</div>
      <Row label="Game updates" value={`${s.gameHz.toFixed(0)}/s`} tone={low(s.gameHz, 50, 25)} />
      <Row label="Pitwall loop" value={`${s.tickHz.toFixed(0)}/s`} tone={low(s.tickHz, 50, 35)} />
      <Row label="Sent to screen" value={`${s.msgsPerS.toFixed(0)}/s`} tone={low(s.msgsPerS, 45, 25)} />
      <Row label="Data age (avg / worst)" value={`${s.ageAvg.toFixed(0)} / ${s.ageMax.toFixed(0)} ms`} tone={bad(s.ageAvg, 40, 80)} />
      <Row label="Longest gap" value={`${s.gapMax.toFixed(0)} ms`} tone={bad(s.gapMax, 60, 120)} />
      <Row label="Screen fps" value={`${fps.current.value.toFixed(0)}`} tone={low(fps.current.value, 50, 30)} />
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="lagm__row">
      <span>{label}</span>
      <b className={tone}>{value}</b>
    </div>
  );
}
