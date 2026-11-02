import { useRig } from "../lib/rig";
import { Card } from "./common";

const CORNERS = ["FL", "FR", "RL", "RR"];

export function Tyres() {
  const f = useRig((s) => s.live.frame);
  const caps = useRig((s) => s.capabilities);
  if (!caps?.reports_tyre_pressure) {
    return (
      <Card title="Tyres" dim>
        <div className="upcoming">This game doesn't report tyre pressures.</div>
      </Card>
    );
  }
  const p = f?.tyre_pressure_psi;
  const t = f?.tyre_core_temp_c;
  return (
    <Card title="Tyres" right="psi · core °C">
      <div className="tyres">
        {CORNERS.map((c, i) => (
          <div key={c} className="tyres__cell">
            <span className="tyres__corner">{c}</span>
            <span className="tyres__psi">{p ? p[i].toFixed(1) : "–"}</span>
            <span className="tyres__temp">{t ? Math.round(t[i]) : "–"}°</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
