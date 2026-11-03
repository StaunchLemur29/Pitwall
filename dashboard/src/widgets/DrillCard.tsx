import { delta, lapTime } from "../lib/format";
import { stopDrill, useRig } from "../lib/rig";
import { Card } from "./common";

/** Section times read better as plain seconds under a minute: "10.62". */
const secs = (ms: number) => (ms < 60000 ? (ms / 1000).toFixed(2) : lapTime(ms));

export function DrillCard() {
  const d = useRig((s) => s.live.track?.drill ?? null);
  const hasTrack = useRig((s) => !!s.track);
  const bound = useRig((s) => (s.config?.bindings.drill_here?.length ?? 0) > 0);

  if (!d) {
    return (
      <Card title="Drill" dim>
        <div className="upcoming">
          {hasTrack
            ? bound
              ? "Press your “drill” button before a corner to practise it, or pick one in analysis."
              : "Pick a corner to practise in analysis, or bind a “drill” button in Settings."
            : "Drills need the track layout."}
        </div>
      </Card>
    );
  }
  const last = d.last;
  return (
    <Card title={`Drill · ${d.name}`} right={<button className="linkbtn" onClick={() => stopDrill()}>stop</button>}>
      <div className="drill">
        <div className="drill__main">
          <div className={`drill__time ${d.running ? "" : "drill__time--idle"}`}>
            {d.running ? d.elapsed_s.toFixed(1) : last ? secs(last.time_ms) : "drive to it"}
          </div>
          {last && !d.running && (
            <div className={`drill__delta ${last.counted ? "good" : "bad"}`}>
              {!last.clean ? "not clean" : last.delta_s === null ? "first run" : delta(last.delta_s)}
            </div>
          )}
        </div>
        <div className="drill__side">
          <div className="drill__best">best {d.best_ms ? secs(d.best_ms) : "—"}</div>
          <div className="drill__streak" aria-label={`${d.streak} of ${d.pass_streak} in a row`}>
            {Array.from({ length: d.pass_streak }, (_, i) => (
              <span key={i} className={`sdot ${i < d.streak ? "sdot--on" : ""}`} />
            ))}
          </div>
          <div className="drill__goal">
            {d.passed ? "Passed ✓" : `${d.pass_streak} clean within ${d.pass_within_s}s of best`}
          </div>
        </div>
      </div>
    </Card>
  );
}
