import { prettyName } from "../lib/format";
import { closeWindow, useRig } from "../lib/rig";
import { LapAnalysis } from "../widgets/LapAnalysis";
import { LapTimes } from "../widgets/LapTimes";
import { RecentLaps } from "../widgets/RecentLaps";

/** Analysis laid out for a wide screen: the main monitor now, the laptop later. */
export function AnalysisPage() {
  const session = useRig((s) => s.session);
  const connected = useRig((s) => s.connected);
  return (
    <div className="apage">
      <header className="apage__top">
        <span className="brand">PITWALL</span>
        <span className="dash__session">
          {session ? `${prettyName(session.car)} · ${prettyName(session.track_key)}` : "Analysis"}
        </span>
        {!connected && <span className="warn">reconnecting…</span>}
        <a className="dash__gear" href="#/settings" title="Settings">
          ⚙
        </a>
        <button className="dash__close" onClick={() => closeWindow("analysis")} title="Close this window" aria-label="Close">
          ✕
        </button>
      </header>
      <div className="apage__grid">
        <div className="apage__main">
          <LapAnalysis wide />
        </div>
        <aside className="apage__side">
          <LapTimes />
          <RecentLaps />
        </aside>
      </div>
    </div>
  );
}
