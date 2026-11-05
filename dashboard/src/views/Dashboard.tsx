import { useEffect, useState } from "react";
import { prettyName } from "../lib/format";
import { minimizeWindow, perf, rig, stopDrill, stopPitwall, useRig } from "../lib/rig";
import { LagMeter } from "../widgets/LagMeter";
import type { Mode } from "../lib/types";
import { WIDGETS } from "../widgets";
import { FullscreenButton } from "../widgets/Fullscreen";
import { PitReportCard } from "../widgets/PitReportCard";

const GAME_NAMES: Record<string, string> = { ac: "Assetto Corsa", demo: "Demo", replay: "Replay" };

export function Dashboard() {
  perf.renders++;
  const connected = useRig((s) => s.connected);
  const config = useRig((s) => s.config);
  const mode = useRig((s) => s.mode);
  const game = useRig((s) => s.game);
  const session = useRig((s) => s.session);
  const status = useRig((s) => s.live.frame?.status ?? "off");
  const stopped = useRig((s) => s.stopped);
  const notice = useRig((s) => s.notice);
  const [, rerender] = useState(0);
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => rerender((n) => n + 1), 4100); // let it expire
    return () => clearTimeout(id);
  }, [notice]);
  // The drill card shrinks to a slim strip while no drill is running.
  const drilling = useRig((s) => !!s.live.track?.drill);
  const layoutMode: Exclude<Mode, "idle"> = mode === "driving" ? "driving" : "analysis";
  const pages = config?.layouts[layoutMode] ?? [];
  const [pageByMode, setPageByMode] = useState<Record<string, number>>({});
  const page = Math.min(pageByMode[layoutMode] ?? 0, Math.max(0, pages.length - 1));

  useEffect(() => {
    const turn = (dir: number) =>
      setPageByMode((p) => {
        const n = pages.length || 1;
        return { ...p, [layoutMode]: ((p[layoutMode] ?? 0) + dir + n) % n };
      });
    const offAction = rig.onAction((a) => {
      if (a === "next_page") turn(1);
      if (a === "prev_page") turn(-1);
    });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === "PageDown") turn(1);
      if (e.key === "ArrowLeft" || e.key === "PageUp") turn(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      offAction();
      window.removeEventListener("keydown", onKey);
    };
  }, [layoutMode, pages.length]);

  // The drill card isn't on the paused / pits layout: keep a way to stop it there.
  const drillName = useRig((s) => s.live.track?.drill?.name ?? null);
  const pitReport = useRig((s) => s.live.pit_report ?? null);
  const slots = pages[page] ?? [];
  const banner = stopped
    ? "Pitwall has stopped. You can close this window."
    : !connected
    ? "Waiting for the Pitwall rig service…"
    : status === "off"
      ? `Waiting for ${GAME_NAMES[game] ?? game} — start a session`
      : status === "paused"
        ? "Paused"
        : status === "replay"
          ? "Replay"
          : notice && Date.now() - notice.at < 4000
            ? notice.text
            : null;

  return (
    <div className={`dash dash--${mode}`}>
      <header className="dash__top">
        <span className="brand">PITWALL</span>
        <span className="dash__session">
          {session ? `${prettyName(session.car)} · ${prettyName(session.track_key)}` : GAME_NAMES[game] ?? ""}
        </span>
        <span className={`dash__mode dash__mode--${mode}`}>{mode}</span>
        <button
          className="dash__open"
          onClick={() => rig.action("open_analysis")}
          title="Open the analysis in a window on your main screen"
        >
          Analysis ↗
        </button>
        <a className="dash__gear" href="#/settings" title="Settings" aria-label="Settings">
          ⚙
        </a>
        <FullscreenButton />
        <button className="dash__close" onClick={() => minimizeWindow("dashboard")} title="Minimise" aria-label="Minimise">
          <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
            <path d="M5 18h14" />
          </svg>
        </button>
        <button
          className="dash__close dash__stop"
          onClick={() => {
            if (confirm("Stop Pitwall? Your laps are already saved.")) void stopPitwall();
          }}
          title="Stop Pitwall"
          aria-label="Stop Pitwall"
        >
          <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
            <path d="M12 3v8" />
            <path d="M6.3 6.8a8 8 0 1 0 11.4 0" />
          </svg>
        </button>
      </header>
      <LagMeter />
      {banner && <div className={`banner ${connected ? "" : "banner--warn"}`}>{banner}</div>}
      {pitReport && mode !== "driving" && <PitReportCard r={pitReport} />}
      {drillName && mode !== "driving" && (
        <div className="banner drillbar">
          <span>
            Drill running: <b>{drillName}</b>
          </span>
          <button className="btn btn--ghost" onClick={() => void stopDrill()}>
            Stop drill
          </button>
        </div>
      )}
      <main className="dash__stack">
        {slots.map((slot, i) => {
          const W = WIDGETS[slot.widget]?.component;
          return (
            <div
              key={`${page}-${i}-${slot.widget}`}
              className="dash__slot"
              style={{ flexGrow: slot.widget === "drill" && !drilling ? Math.min(slot.size, 0.8) : slot.size }}
            >
              {W ? <W /> : null}
            </div>
          );
        })}
      </main>
      {pages.length > 1 && (
        <nav className="dots" aria-label="Pages">
          {pages.map((_, i) => (
            <button
              key={i}
              className={`dots__dot ${i === page ? "dots__dot--on" : ""}`}
              onClick={() => setPageByMode((p) => ({ ...p, [layoutMode]: i }))}
              aria-label={`Page ${i + 1}`}
            />
          ))}
        </nav>
      )}
    </div>
  );
}
