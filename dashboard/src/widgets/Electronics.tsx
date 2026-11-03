import { useRig } from "../lib/rig";
import { Card } from "./common";

/** BB / ABS / TC as the car currently has them. Suggestions arrive in phase 3. */
export function Electronics() {
  const f = useRig((s) => s.live.frame);
  const caps = useRig((s) => s.capabilities);
  if (!caps || !(caps.reports_brake_bias || caps.reports_abs_level || caps.reports_tc_level)) {
    return (
      <Card title="Electronics" dim>
        <div className="upcoming">This game doesn't report brake bias, ABS or TC.</div>
      </Card>
    );
  }
  const bb = f?.brake_bias;
  return (
    <Card title="Electronics">
      <div className="elec">
        {caps.reports_brake_bias && (
          <Item label="Brake bias" value={bb ? (bb * 100).toFixed(1) : "–"} unit={bb ? "% F" : ""} />
        )}
        {caps.reports_abs_level && <Item label="ABS" value={level(f?.abs)} active={f?.abs_active} />}
        {caps.reports_tc_level && <Item label="TC" value={level(f?.tc)} active={f?.tc_active} />}
      </div>
    </Card>
  );
}

// AC only reports a raw slip setting, not the level on your dial, so we show
// on/off here. Real levels come with the in-game CSP companion app.
function level(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return v <= 0 ? "OFF" : "ON";
}

function Item({ label, value, unit, active }: { label: string; value: string; unit?: string; active?: boolean }) {
  return (
    <div className={`elec__item ${active ? "elec__item--active" : ""}`}>
      <div className="elec__label">{label}</div>
      <div className="elec__value">
        {value}
        {unit && <span className="elec__unit">{unit}</span>}
      </div>
    </div>
  );
}
