import { useEffect, useState } from "react";
import { clock, delta, lapTime } from "../lib/format";
import { useRig } from "../lib/rig";

/**
 * One thin row of the things that rarely change, for a glance between corners:
 * this lap, last and best, delta, brake bias / ABS / TC, and time driving.
 */
export function StatusLine() {
  const live = useRig((s) => s.live);
  const caps = useRig((s) => s.capabilities);
  const breakMin = useRig((s) => s.config?.session_timer.break_reminder_min ?? 0);
  const lastLap = useRig((s) => s.lastLap);
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const f = live.frame;
  const running = !!f && f.status !== "off" && !f.in_pit_box && f.lap_time_ms > 0;
  const d = live.delta_s;
  const el = live.electronics; // real levels when the in-game app is running
  const bb = el?.bb ?? f?.brake_bias;
  const breakDue = breakMin > 0 && live.driving_s >= breakMin * 60;
  const flash = lastLap && Date.now() - lastLap.at < 6000 ? lastLap : null;

  return (
    <section className={`card status ${breakDue ? "status--break" : ""}`}>
      <div className="status__row">
        <Item label={running && f ? `Lap ${f.lap + 1}` : "Lap"} value={running ? lapTime(f?.lap_time_ms) : "—"} />
        {d !== null && <Item label="Δ" value={delta(d)} tone={d < -0.005 ? "good" : d > 0.005 ? "bad" : ""} />}
        <Item
          label="Last"
          value={lapTime(f?.last_lap_ms || lastLap?.lap.lap_time_ms)}
          tone={flash ? (flash.newBest ? "best" : flash.lap.valid ? "" : "bad") : ""}
        />
        <Item label="Best" value={lapTime(live.ref_lap_ms)} tone="best" />
      </div>
      <div className="status__row">
        {caps?.reports_brake_bias && <Item label="BB" value={bb ? (bb * 100).toFixed(1) : "–"} />}
        {caps?.reports_abs_level && (
          <Item label="ABS" value={el ? level(el.abs, el.abs_modes) : onOff(f?.abs)} tone={f?.abs_active ? "warn" : ""} />
        )}
        {caps?.reports_tc_level && (
          <Item label="TC" value={el ? level(el.tc, el.tc_modes) : onOff(f?.tc)} tone={f?.tc_active ? "warn" : ""} />
        )}
        {el?.drs_present && (
          <Item label="DRS" value={el.drs_active ? "OPEN" : el.drs_available ? "READY" : "–"} tone={el.drs_active ? "good" : el.drs_available ? "warn" : ""} />
        )}
        {el?.kers_present && el.kers_charge != null && <Item label="Batt" value={`${Math.round(el.kers_charge * 100)}%`} />}
        {el?.mguk_delivery_count ? <Item label="Deploy" value={String(el.mguk_delivery ?? "–")} /> : null}
        {el?.engine_brake_count && el.engine_brake_count > 1 ? <Item label="EB" value={String(el.engine_brake ?? "–")} /> : null}
        <Item label={breakDue ? "Break" : "Driving"} value={clock(live.driving_s)} tone={breakDue ? "warn" : ""} />
      </div>
    </section>
  );
}

/** The level on your dial, from the in-game app: "3", or "OFF". */
export function level(v: number | null | undefined, modes: number | null | undefined): string {
  if (v === null || v === undefined || !modes) return "–";
  return v <= 0 ? "OFF" : String(v);
}

// AC only reports a raw slip setting, so on/off until the CSP app sends real levels.
function onOff(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return v <= 0 ? "OFF" : "ON";
}

function Item({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <span className={`status__item ${tone ? `status__item--${tone}` : ""}`}>
      <b>{label}</b>
      {value}
    </span>
  );
}
