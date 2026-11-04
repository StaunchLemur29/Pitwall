import { delta, lapTime } from "../lib/format";
import { stopDrill, useRig } from "../lib/rig";
import type { Attempt } from "../lib/types";
import { Card } from "./common";

/** Section times read better as plain seconds under a minute: "10.62". */
const secs = (ms: number) => (ms < 60000 ? (ms / 1000).toFixed(2) : lapTime(ms));

export function DrillCard() {
  const d = useRig((s) => s.live.track?.drill ?? null);
  const hasTrack = useRig((s) => !!s.track);
  const bound = useRig((s) => (s.config?.bindings.drill_here?.length ?? 0) > 0);
  const retry = useRig((s) => s.retry);

  if (!d) {
    // No drill running: this strip is where coaching tips will appear (phase 3).
    return (
      <Card title="Coach" dim>
        <div className="upcoming upcoming--left">
          {hasTrack
            ? bound
              ? "Press your drill button before a section to practise it, or pick one in analysis."
              : "Pick a section to practise in analysis, or bind a drill button in Settings."
            : "Drills need the track layout."}
        </div>
      </Card>
    );
  }
  const last = d.last;
  const retryMsg =
    retry && Date.now() - retry.at < 5000
      ? {
          rewinding: "Rewinding to the start…",
          ready: "Ready — go!",
          no_rewind: "Time Shift didn't rewind — check its key matches Settings → Controls",
          timeout: "Rewind took too long — stopped",
          stopped: "",
          teleporting: "Teleporting…",
          teleported: "You're there — pull away when ready",
          no_teleport: "Couldn't teleport — only works in offline practice",
        }[retry.state] ?? ""
      : "";
  return (
    <Card title={`Drill · ${d.name}`} right={<button className="linkbtn" onClick={() => stopDrill()}>stop</button>}>
      <div className="drill">
        <div className="drill__main">
          <div className={`drill__time ${d.running ? "" : "drill__time--idle"}`}>
            {d.running ? d.elapsed_s.toFixed(1) : last ? secs(last.time_ms) : "drive to it"}
          </div>
          {last && !d.running && (
            <div className={`drill__delta ${!last.clean ? "amber" : last.new_best ? "good" : "drill__delta--plain"}`}>
              {!last.clean
                ? "not clean"
                : last.delta_s === null
                  ? "first run"
                  : last.new_best
                    ? `new best ${delta(last.delta_s)}`
                    : `${delta(last.delta_s)} to best`}
            </div>
          )}
        </div>
        <div className="drill__side">
          <div className="drill__best">best {d.best_ms ? secs(d.best_ms) : "—"}</div>
          {d.recent.length > 0 && <RecentRuns runs={d.recent} />}
          {retryMsg && <div className="drill__retry">{retryMsg}</div>}
          <div className="drill__goal">{d.attempts ? `${d.attempts} run${d.attempts === 1 ? "" : "s"}` : "drive through it"}</div>
        </div>
      </div>
    </Card>
  );
}

/** Your last few runs as bars (taller = quicker), oldest first. Nothing ever resets. */
function RecentRuns({ runs }: { runs: Attempt[] }) {
  const clean = runs.filter((r) => r.clean).map((r) => r.time_ms);
  const lo = clean.length ? Math.min(...clean) : 0;
  const hi = clean.length ? Math.max(...clean) : 0;
  const h = (r: Attempt) => (!r.clean || hi === lo ? 0.55 : 0.3 + (0.7 * (hi - r.time_ms)) / (hi - lo));
  return (
    <div className="druns" aria-label="Your recent runs">
      {runs.map((r, i) => (
        <span
          key={i}
          className={`druns__bar ${!r.clean ? "druns__bar--cut" : r.new_best ? "druns__bar--best" : ""}`}
          style={{ height: `${Math.round(h(r) * 100)}%` }}
          title={`${secs(r.time_ms)}${r.clean ? "" : " (not clean)"}`}
        />
      ))}
    </div>
  );
}
