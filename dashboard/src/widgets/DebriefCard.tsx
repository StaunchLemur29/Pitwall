/** The AI debrief for this car + track: the latest one, earlier ones underneath. */
import { Fragment, useEffect, useState, type ReactNode } from "react";
import type { Combo } from "../lib/rig";
import { useSource } from "../lib/source";
import type { Debrief } from "../lib/types";
import { Panel } from "./Panel";

const when = (t: number) =>
  new Date(t * 1000).toLocaleString("en-NZ", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

/** The small bit of Markdown debriefs use: **bold**, bullets, paragraphs. Text only, never HTML. */
export function Markdown({ text }: { text: string }) {
  const inline = (s: string): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : <Fragment key={i}>{part}</Fragment>,
    );
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) blocks.push(<ul key={blocks.length}>{bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}</ul>);
    bullets = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const m = line.match(/^[-*•]\s+(.*)$/);
    if (m) bullets.push(m[1]);
    else {
      flush();
      if (line) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <div className="md">{blocks}</div>;
}

export function DebriefCard({ combo, panel = false }: { combo: Combo | null; panel?: boolean }) {
  const src = useSource();
  const [list, setList] = useState<Debrief[] | null>(null);
  const [canWrite, setCanWrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [older, setOlder] = useState(false);
  const key = combo ? `${combo.game}|${combo.car}|${combo.track_key}` : "";
  useEffect(() => {
    if (!combo) return;
    let ok = true;
    setList(null);
    setErr(null);
    src.debriefs(combo).then((d) => ok && setList(d)).catch(() => ok && setList([]));
    src.canWriteDebrief?.().then((c) => ok && setCanWrite(c));
    return () => {
      ok = false;
    };
  }, [src, key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!combo || list === null) return null;
  const write = async () => {
    if (!src.writeDebrief) return;
    setBusy(true);
    setErr(null);
    try {
      const d = await src.writeDebrief(combo);
      setList((l) => [d, ...(l ?? []).filter((x) => x.session_start !== d.session_start)]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };
  const [latest, ...rest] = list;
  // Hub without debriefs set up (README, AI debrief) and nothing written yet: nothing to show.
  if (!latest && !(src.writeDebrief && (canWrite || src.live))) return null;
  const head = (
    <>
      {latest && <span className="muted debrief__when">session {when(latest.session_start)}</span>}
      {src.writeDebrief && canWrite && (
        <button className="btn btn--sm btn--ghost" disabled={busy} onClick={write}>
          {busy ? "Writing…" : latest ? "Rewrite" : "Write debrief"}
        </button>
      )}
    </>
  );
  const body = (
    <div className="debrief">
      {!panel && (
        <div className="debrief__head">
          <span className="chapters__title">Debrief</span>
          {head}
        </div>
      )}
      {latest ? (
        <Markdown text={latest.body} />
      ) : (
        <p className="muted debrief__empty">
          {canWrite
            ? src.live
              ? "No debrief for this car + track yet. One is written automatically when a session ends (3+ clean laps), or press Write debrief."
              : "No debrief for this car + track yet. Press Write debrief for your latest session (3+ clean laps)."
            : "Add your Anthropic API key in Settings → AI to get a race-engineer debrief after each session."}
        </p>
      )}
      {err && <p className="warn">{err}</p>}
      {rest.length > 0 && (
        <button className="linkbtn" onClick={() => setOlder((o) => !o)}>
          {older ? "Hide earlier debriefs" : `Earlier debriefs (${rest.length})`}
        </button>
      )}
      {older &&
        rest.map((d) => (
          <div key={d.session_start} className="debrief__old">
            <div className="muted debrief__when">session {when(d.session_start)}</div>
            <Markdown text={d.body} />
          </div>
        ))}
    </div>
  );
  return panel ? <Panel id="debrief" title="Debrief" right={head}>{body}</Panel> : body;
}
