import { useEffect, useState } from "react";
import { prettyName } from "../lib/format";
import { rig, useRig } from "../lib/rig";
import type { Mode } from "../lib/types";
import { WIDGETS } from "../widgets";

const GAME_NAMES: Record<string, string> = { ac: "Assetto Corsa", demo: "Demo", replay: "Replay" };

export function Dashboard() {
  const connected = useRig((s) => s.connected);
  const config = useRig((s) => s.config);
  const mode = useRig((s) => s.mode);
  const game = useRig((s) => s.game);
  const session = useRig((s) => s.session);
  const status = useRig((s) => s.live.frame?.status ?? "off");
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

  const slots = pages[page] ?? [];
  const banner = !connected
    ? "Waiting for the Pitwall rig service…"
    : status === "off"
      ? `Waiting for ${GAME_NAMES[game] ?? game} — start a session`
      : status === "paused"
        ? "Paused"
        : status === "replay"
          ? "Replay"
          : null;

  return (
    <div className={`dash dash--${mode}`}>
      <header className="dash__top">
        <span className="brand">PITWALL</span>
        <span className="dash__session">
          {session ? `${prettyName(session.car)} · ${prettyName(session.track_key)}` : GAME_NAMES[game] ?? ""}
        </span>
        <span className={`dash__mode dash__mode--${mode}`}>{mode}</span>
        <a className="dash__gear" href="#/settings" title="Settings" aria-label="Settings">
          ⚙
        </a>
      </header>
      {banner && <div className={`banner ${connected ? "" : "banner--warn"}`}>{banner}</div>}
      <main className="dash__stack">
        {slots.map((slot, i) => {
          const W = WIDGETS[slot.widget]?.component;
          return (
            <div key={`${page}-${i}-${slot.widget}`} className="dash__slot" style={{ flexGrow: slot.size }}>
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
