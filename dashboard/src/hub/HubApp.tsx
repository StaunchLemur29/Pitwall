/**
 * The hub: your laps from the cloud, on the MacBook (or anywhere) while the rig
 * PC is off. Same analysis as the main-screen window on the PC, read-only.
 */
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useMemo, useState } from "react";
import { prettyName } from "../lib/format";
import { SourceContext } from "../lib/source";
import { LapAnalysis } from "../widgets/LapAnalysis";
import { Progress } from "./Progress";
import { hubSource } from "./source";

const URL_ = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export function HubApp() {
  const sb = useMemo(() => (URL_ && KEY ? createClient(URL_, KEY) : null), []);
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  useEffect(() => {
    if (!sb) return;
    sb.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, [sb]);

  if (!sb) {
    return (
      <Shell>
        <div className="hub__msg">
          The hub isn't set up yet: it needs <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> (see the README, “Cloud hub”).
        </div>
      </Shell>
    );
  }
  if (session === undefined) return <Shell><div className="hub__msg">Loading…</div></Shell>;
  if (!session) return <Login sb={sb} />;
  return <Hub sb={sb} email={session.user.email ?? ""} />;
}

function Shell({ children, title, left, right }: { children: React.ReactNode; title?: string; left?: React.ReactNode; right?: React.ReactNode }) {
  // Three columns: logo | title centred on the window | account. The outer two
  // share the leftover space equally, so the title stays dead centre.
  return (
    <div className="apage hub">
      <header className="hub__top">
        <span className="hub__left">
          <span className="brand">PITWALL</span>
          <span className="dash__session">hub</span>
          {left}
        </span>
        <span className="hub__title">{title}</span>
        <span className="hub__right">{right}</span>
      </header>
      {children}
    </div>
  );
}

function Login({ sb }: { sb: SupabaseClient }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const { error } = await sb.auth.signInWithPassword({ email, password });
    if (error) setErr(error.message);
    setBusy(false);
  };
  return (
    <Shell>
      <form className="card hub__login" onSubmit={go}>
        <div className="card__title">Sign in</div>
        <p className="field__hint">The same email and password you connected Pitwall with.</p>
        <label className="field">
          <span className="field__label">Email</span>
          <input className="textin" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Password</span>
          <input className="textin" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {err && <p className="warn">{err}</p>}
        <button className="btn" disabled={busy || !email || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </Shell>
  );
}

function Hub({ sb, email }: { sb: SupabaseClient; email: string }) {
  const source = useMemo(() => hubSource(sb), [sb]);
  const [showing, setShowing] = useState<{ car: string; track_key: string } | null>(null);
  const [view, setView] = useState<"analysis" | "progress">(() => (location.hash === "#progress" ? "progress" : "analysis"));
  const go = (v: "analysis" | "progress") => {
    setView(v);
    history.replaceState(null, "", v === "progress" ? "#progress" : "#");
  };
  const [wide, setWide] = useState(() => window.innerWidth >= 1100);
  useEffect(() => {
    const on = () => setWide(window.innerWidth >= 1100);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  useEffect(() => {
    document.title = showing ? `${prettyName(showing.track_key)} · Pitwall hub` : "Pitwall hub";
  }, [showing]);
  return (
    <SourceContext.Provider value={source}>
      <Shell
        title={view === "analysis" && showing ? `${prettyName(showing.car)} · ${prettyName(showing.track_key)}` : ""}
        left={
          <nav className="hub__tabs">
            {(["analysis", "progress"] as const).map((v) => (
              <button key={v} className={`chipbtn ${view === v ? "chipbtn--on" : ""}`} onClick={() => go(v)}>
                {v === "analysis" ? "Analysis" : "Progress"}
              </button>
            ))}
          </nav>
        }
        right={
          <>
            <span className="muted hub__email">{email}</span>
            <button className="btn btn--sm btn--ghost" onClick={() => sb.auth.signOut()}>Sign out</button>
          </>
        }
      >
        <div className={`hub__main ${wide ? "" : "hub__main--narrow"}`}>
          {view === "analysis" ? <LapAnalysis wide={wide} onShowing={setShowing} /> : <Progress />}
        </div>
      </Shell>
    </SourceContext.Provider>
  );
}
