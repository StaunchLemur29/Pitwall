import { useEffect, useState } from "react";
import { clock } from "../lib/format";
import { useRig } from "../lib/rig";

/** Rig time, driving time, session time left, optional break reminder. Music lands here in phase 3. */
export function SessionBar() {
  const startedAt = useRig((s) => s.startedAt);
  const drivingS = useRig((s) => s.live.driving_s);
  const left = useRig((s) => s.live.frame?.session_time_left_s ?? null);
  const timer = useRig((s) => s.live.timer);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);
  const breakDue = !!timer?.break_due;
  const race = timer?.race;

  return (
    <section className={`sbar ${breakDue ? "sbar--break" : ""}`}>
      <span>
        <b>On rig</b> {clock(now - startedAt)}
      </span>
      <span>
        <b>Driving</b> {clock(drivingS)}
      </span>
      {timer && (
        <span>
          <b>Stint</b> {clock(timer.stint_s)}
        </span>
      )}
      {race?.laps_left != null ? (
        <span>
          <b>Laps left</b> {race.laps_left}
        </span>
      ) : (
        left !== null && (
          <span>
            <b>Left</b> {clock(left)}
          </span>
        )
      )}
      {race?.position ? (
        <span>
          <b>Pos</b> P{race.position}
        </span>
      ) : null}
      {breakDue && <span className="sbar__break">Time for a break</span>}
    </section>
  );
}
