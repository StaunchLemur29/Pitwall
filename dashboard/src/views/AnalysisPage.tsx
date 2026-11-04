import { useState } from "react";
import { prettyName } from "../lib/format";
import { closeWindow, useRig } from "../lib/rig";
import { LapAnalysis } from "../widgets/LapAnalysis";
import { LapTimes } from "../widgets/LapTimes";
import { RecentLaps } from "../widgets/RecentLaps";
import { FullscreenButton } from "../widgets/Fullscreen";

/** Analysis laid out for a wide screen: the main monitor now, the laptop later. */
export function AnalysisPage() {
  const session = useRig((s) => s.session);
  const connected = useRig((s) => s.connected);
  const [showing, setShowing] = useState<{ car: string; track_key: string } | null>(null);
  const title = showing ?? session;
  return (
    <div className="apage">
      <header className="apage__top">
        <span className="brand">PITWALL</span>
        <span className="dash__session">
          {title ? `${prettyName(title.car)} · ${prettyName(title.track_key)}` : "Analysis"}
        </span>
        {!connected && <span className="warn">reconnecting…</span>}
        <a className="dash__gear" href="#/settings" title="Settings">
          ⚙
        </a>
        <FullscreenButton />
        <button className="dash__close" onClick={() => closeWindow("analysis")} title="Close this window" aria-label="Close">
          ✕
        </button>
      </header>
      <div className="apage__grid">
        <div className="apage__main">
          <LapAnalysis wide onShowing={setShowing} />
        </div>
        <aside className="apage__side">
          <LapTimes />
          <RecentLaps />
        </aside>
      </div>
    </div>
  );
}
