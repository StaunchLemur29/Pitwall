import { delta, lapTime } from "../lib/format";
import { useRig } from "../lib/rig";
import { Card } from "./common";

export function LapTimes() {
  const live = useRig((s) => s.live);
  const lastLap = useRig((s) => s.lastLap);
  const f = live.frame;
  const d = live.delta_s;
  const tone = d === null ? "" : d < -0.005 ? "good" : d > 0.005 ? "bad" : "";
  const running = !!f && f.status !== "off" && !f.in_pit_box && f.lap_time_ms > 0;
  const flash = lastLap && Date.now() - lastLap.at < 6000 ? lastLap : null;

  return (
    <Card title={running && f ? `Lap ${f.lap + 1}` : "Laps"} right={live.ref_lap_ms ? `vs best ${lapTime(live.ref_lap_ms)}` : "no reference yet"}>
      <div className="laps">
        {running ? (
          <>
            <div className="laps__now">{lapTime(f?.lap_time_ms)}</div>
            <div className={`laps__delta laps__delta--${tone}`}>{d === null ? "" : delta(d)}</div>
          </>
        ) : (
          <div className="laps__idle">{live.ref_lap_ms ? "Your best on this car and track" : "No laps yet"}</div>
        )}
        <div className="laps__grid">
          <Stat label="Last" value={lapTime(f?.last_lap_ms || lastLap?.lap.lap_time_ms)} tone={flash ? (flash.newBest ? "best" : flash.lap.valid ? "" : "bad") : ""} />
          <Stat label="Best" value={lapTime(live.ref_lap_ms)} />
          <Stat label="Optimal" value={lapTime(live.theoretical_best_ms)} />
        </div>
        {flash && (
          <div className={`laps__flash ${flash.newBest ? "laps__flash--best" : ""}`}>
            {flash.newBest ? "New personal best" : flash.lap.out_lap ? "Out lap" : flash.lap.rewound && flash.lap.valid ? "Rewind used: not a best" : flash.lap.valid ? "Lap complete" : "Lap invalid (track limits)"}
          </div>
        )}
      </div>
    </Card>
  );
}

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`stat stat--${tone}`}>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
    </div>
  );
}
