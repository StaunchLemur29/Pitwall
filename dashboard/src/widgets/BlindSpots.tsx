/** Blind spots: habits across your recent laps here (rig scan.py), each with
 * where it shows most and the drill to fix it. PC only. */
import { useEffect, useState } from "react";
import { practise, type Combo } from "../lib/rig";
import type { AnalysisSource } from "../lib/source";
import type { BlindSpot } from "../lib/types";

export function BlindSpots({ src, combo, refresh, canDrill }: { src: AnalysisSource; combo: Combo | null; refresh: unknown; canDrill: boolean }) {
  const [found, setFound] = useState<{ findings: BlindSpot[]; laps: number } | null>(null);
  useEffect(() => {
    if (!src.blindSpots) return;
    let live = true;
    src.blindSpots(combo).then((r) => live && setFound(r));
    return () => {
      live = false;
    };
  }, [src, combo?.game, combo?.car, combo?.track_key, refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!found) return <p className="muted">Looking…</p>;
  if (!found.findings.length)
    return (
      <p className="muted">
        {found.laps < 6 ? "Drive a few more laps here and Pitwall will look for habits." : `Nothing that's a habit across your last ${found.laps} laps.`}
      </p>
    );
  return (
    <div className="blind">
      {found.findings.map((f) => (
        <div key={f.key} className="blind__item">
          <div className="blind__head">
            <b>{f.title}</b>
            {f.drill && canDrill && (
              <button className="btn btn--sm" onClick={() => practise({ section: f.drill!.number }, f.drill!.name)}>
                Practise {f.drill.name}
              </button>
            )}
          </div>
          <div>{f.detail}</div>
          {f.corners.length > 0 && <div className="muted">Shows most at {f.corners.join(", ")}.</div>}
          <div className="blind__why">{f.why}</div>
        </div>
      ))}
    </div>
  );
}
