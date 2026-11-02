import { useRig } from "../lib/rig";
import { Card } from "./common";

/**
 * Phase 0 stand-in for the next-corner card: shows where you are on the lap.
 * Corner detection (phase 1) replaces this with the upcoming corner.
 */
export function NextCorner() {
  const f = useRig((s) => s.live.frame);
  const sectors = useRig((s) => s.session?.sector_count ?? 0);
  const pct = f ? Math.round(f.lap_progress * 100) : 0;
  return (
    <Card title="Next corner" right={<span className="pill">corners in phase 1</span>}>
      <div className="nextc">
        <div className="nextc__main">
          {sectors > 0 && f ? `Sector ${f.sector + 1}` : "—"}
          <span className="nextc__sub">{f ? `${pct}% of lap` : ""}</span>
        </div>
        <div className="nextc__bar">
          <div className="nextc__fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
    </Card>
  );
}
