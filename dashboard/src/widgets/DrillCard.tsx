import { delta, lapTime } from "../lib/format";
import { practise, stopDrill, useRig } from "../lib/rig";
import type { Attempt } from "../lib/types";
import { Card } from "./common";

/** Section times read better as plain seconds under a minute: "10.62". */
const secs = (ms: number) => (ms < 60000 ? (ms / 1000).toFixed(2) : lapTime(ms));

export function DrillCard() {
  const d = useRig((s) => s.live.track?.drill ?? null);
  const hasTrack = useRig((s) => !!s.track);
  const bound = useRig((s) => (s.config?.bindings.drill_here?.length ?? 0) > 0);
  const retry = useRig((s) => s.retry);
  const coach = useRig((s) => s.live.coach);

  if (!d) {
    // No drill running: the coach strip. Cold tyres first, then the lap just
    // finished (for a moment), else the session's one focus corner.
    // One thing at a time: cold tyres alone; then the lap just finished; then the focus.
    const cold = !!coach?.tyres?.cold;
    const last = cold ? null : coach?.last_lap;
    const focus = cold ? null : coach?.focus;
    const busy = cold || !!last || !!focus;
    return (
      <Card title={busy ? undefined : "Coach"} dim={!busy} className={busy ? "coach" : ""}>
        {cold ? (
          <div className="coach__warn">
            <span className="coach__tag">Tyres</span>
            Cold{coach!.tyres!.avg_c ? ` (${coach!.tyres!.avg_c}°)` : ""}: build up, they work at about {coach!.tyres!.working_c}°
          </div>
        ) : last ? (
          <div className="coach__lap">
            <span className="coach__tag">Lap {last.lap}</span>
            {last.wrong ? (
              <>
                <b>{last.wrong.label}</b> <span className="coach__why">{last.wrong.text}</span>
              </>
            ) : (
              <span className="good">Clean: every corner within your usual.</span>
            )}
          </div>
        ) : focus ? (
          <div className="coach__focus">
            <div className="coach__head">
              <span className="coach__tag">Focus</span>
              <b>{focus.label}</b>
              <span className="coach__target">
                to beat {focus.to_beat_s.toFixed(2)}s <span className="muted">(usual {focus.usual_s.toFixed(2)})</span>
              </span>
              {focus.section && (
                <button className="btn btn--sm" onClick={() => practise({ section: focus.section!.number }, focus.section!.name)}>
                  Practise
                </button>
              )}
            </div>
            <div className="coach__why">{focus.fix ?? focus.why}</div>
          </div>
        ) : (
          <div className="upcoming upcoming--left">
            {hasTrack
              ? bound
                ? "Press your drill button before a section to practise it, or pick one in analysis."
                : "Pick a section to practise in analysis, or bind a drill button in Settings."
              : "Drills need the track layout."}
          </div>
        )}
      </Card>
    );
  }
  const last = d.last;
  // The time to beat only means something while it's quicker than your best run.
  const target = d.target_ms && (!d.best_ms || d.target_ms < d.best_ms) ? d.target_ms : null;
  const vsTarget = target && last ? (last.time_ms - target) / 1000 : null;
  const beat = !!last && last.clean && vsTarget !== null && vsTarget <= 0;
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
          teleported_cold: "You're there — tyres are cold (this CSP can't warm them)",
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
            <div className={`drill__delta ${!last.clean ? "amber" : beat || last.new_best ? "good" : "drill__delta--plain"}`}>
              {!last.clean
                ? "not clean"
                : vsTarget !== null
                  ? beat
                    ? `beat it by ${Math.abs(vsTarget).toFixed(2)}${last.new_best ? " · new best" : ""}`
                    : `${delta(vsTarget)} to beat${last.new_best ? " · new best" : ""}`
                  : last.delta_s === null
                    ? "first run"
                    : last.new_best
                      ? `new best ${delta(last.delta_s)}`
                      : `${delta(last.delta_s)} to best`}
            </div>
          )}
        </div>
        <div className="drill__side">
          {target ? <div className="drill__target">to beat {secs(target)}</div> : null}
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
