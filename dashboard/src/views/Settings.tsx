import { Fragment, useEffect, useState } from "react";
import { cancelBinding, inputDevices, resetConfig, saveConfig, startBinding, useRig } from "../lib/rig";
import type { Binding, Config, WidgetId, WidgetSlot } from "../lib/types";
import { WIDGETS } from "../widgets";
import { FullscreenButton } from "../widgets/Fullscreen";

type Tab = "general" | "layout" | "controls" | "cloud" | "ai" | "advanced";

export function Settings() {
  const live = useRig((s) => s.config);
  const actions = useRig((s) => s.actions);
  const bindingAction = useRig((s) => s.bindingAction);
  const [draft, setDraft] = useState<Config | null>(live);
  const [tab, setTab] = useState<Tab>("general");
  const [errors, setErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  // Pick up server-side changes (e.g. a new wheel binding) when we have no unsaved edits.
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (!dirty) setDraft(live);
  }, [live, dirty]);

  if (!draft) return <div className="settings">Connecting…</div>;

  const edit = (fn: (c: Config) => void) => {
    const next = structuredClone(draft);
    fn(next);
    setDraft(next);
    setDirty(true);
    setSaved(false);
  };

  const save = async () => {
    const errs = await saveConfig(draft);
    setErrors(errs);
    if (!errs.length) {
      setDirty(false);
      setSaved(true);
    }
  };

  return (
    <div className="settings">
      <header className="settings__head">
        <a href="#/" className="settings__back">
          ← Dashboard
        </a>
        <h1>Settings</h1>
        <div className="settings__actions">
          <FullscreenButton className="btn btn--ghost" />
          {saved && !dirty && <span className="ok">Saved</span>}
          <button
            className="btn btn--ghost"
            onClick={() => {
              setDraft(live);
              setDirty(false);
              setErrors([]);
            }}
            disabled={!dirty}
          >
            Discard
          </button>
          <button className="btn" onClick={save} disabled={!dirty}>
            Save
          </button>
        </div>
      </header>

      {errors.length > 0 && (
        <ul className="errors">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <nav className="tabs">
        {(["general", "layout", "controls", "cloud", "ai", "advanced"] as Tab[]).map((t) => (
          <button key={t} className={`tabs__tab ${tab === t ? "tabs__tab--on" : ""}`} onClick={() => setTab(t)}>
            {t === "ai" ? "AI" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      <div className="settings__card">
      {tab === "general" && <General draft={draft} edit={edit} />}
      {tab === "layout" && <Layout draft={draft} edit={edit} />}
      {tab === "controls" && (
        <Controls draft={draft} edit={edit} actions={actions} bindingAction={bindingAction} dirty={dirty} />
      )}
      {tab === "cloud" && <Cloud />}
      {tab === "ai" && <AI />}
      {tab === "advanced" && (
        <Advanced
          draft={draft}
          edit={edit}
          onReset={async () => {
            if (confirm("Reset every setting to its default?")) {
              await resetConfig();
              setDirty(false);
            }
          }}
        />
      )}
      </div>
    </div>
  );
}

interface CloudStatus {
  connected: boolean;
  state: "off" | "idle" | "syncing" | "error";
  error?: string | null;
  email?: string | null;
  url?: string | null;
  last_sync?: number | null;
  pending?: number;
  demo?: boolean;
}

/** Cloud sync to the hub: connect once, then laps upload in the background. */
function Cloud() {
  const [st, setSt] = useState<CloudStatus | null>(null);
  const [form, setForm] = useState({ url: "", anon_key: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = () => fetch("/api/cloud").then((r) => r.json()).then(setSt).catch(() => {});
  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);
  const post = async (path: string, body?: unknown) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      const j = await r.json();
      if (!r.ok) setErr(j.error ?? "Something went wrong");
      else {
        setSt(j);
        setForm((f) => ({ ...f, password: "" }));
      }
    } catch {
      setErr("Couldn't reach the Pitwall service");
    }
    setBusy(false);
  };
  if (!st) return <div className="panel">Loading…</div>;
  if (st.demo) return <div className="panel"><p className="field__hint">Cloud sync is off in demo mode (demo laps stay on this PC).</p></div>;

  if (st.connected) {
    const when = st.last_sync ? new Date(st.last_sync * 1000).toLocaleString("en-NZ") : "not yet";
    return (
      <div className="panel">
        <p>
          <span className={st.state === "error" ? "bad" : "good"}>●</span> Syncing to the hub as <b>{st.email}</b>
        </p>
        <p className="field__hint">
          Project: {st.url}
          <br />
          Last upload: {when} · Laps waiting: {st.pending ?? 0}
          {st.state === "syncing" ? " · uploading now…" : ""}
        </p>
        {st.state === "error" && st.error && <p className="warn">Last try failed: {st.error}. It retries on its own.</p>}
        <div className="row">
          <button className="btn" disabled={busy} onClick={() => post("/api/cloud/sync")}>Sync now</button>
          <button className="btn btn--ghost" disabled={busy} onClick={() => confirm("Stop syncing to the hub? Laps stay on this PC.") && post("/api/cloud/disconnect")}>
            Disconnect
          </button>
        </div>
      </div>
    );
  }
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <div className="panel">
      <p className="field__hint">
        Uploads your laps to your own Supabase project so the hub (on the MacBook) can show them while this PC is off.
        Set-up steps are in the README under “Cloud hub”. Your password is only used to sign in once; it isn't saved.
      </p>
      <Field label="Supabase project URL" hint="Project Settings → API → Project URL, like https://abcd1234.supabase.co">
        <input className="textin" value={form.url} onChange={set("url")} placeholder="https://….supabase.co" />
      </Field>
      <Field label="Anon (public) key" hint="Project Settings → API → anon public key. It's meant to be public: the database only lets your login see your data.">
        <input className="textin" value={form.anon_key} onChange={set("anon_key")} />
      </Field>
      <Field label="Email">
        <input className="textin" type="email" value={form.email} onChange={set("email")} />
      </Field>
      <Field label="Password">
        <input className="textin" type="password" value={form.password} onChange={set("password")} />
      </Field>
      {err && <p className="warn">{err}</p>}
      <div className="row">
        <button className="btn" disabled={busy} onClick={() => post("/api/cloud/connect", form)}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </div>
    </div>
  );
}

interface AIStatus {
  configured: boolean;
  key_hint?: string | null;
  auto?: boolean;
  model?: string;
  state?: string;
  error?: string | null;
  available?: boolean;
}

/** The AI debrief: your Anthropic API key (kept on this PC only) and automatic debriefs. */
function AI() {
  const [st, setSt] = useState<AIStatus | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/ai").then((r) => r.json()).then(setSt).catch(() => {});
  }, []);
  const post = async (body: unknown) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok) setErr(j.error ?? "Something went wrong");
      else {
        setSt(j);
        setKey("");
      }
    } catch {
      setErr("Couldn't reach the Pitwall service");
    }
    setBusy(false);
  };
  if (!st) return <div className="panel">Loading…</div>;
  return (
    <div className="panel">
      <p className="field__hint">
        After a session with at least 3 clean laps, Claude writes a short race-engineer debrief: the one thing worth the most
        time, a couple of smaller notes, what's going well, and a section to drill. It appears in the analysis here and in the hub.
        Each debrief costs roughly 10 cents, billed to your Anthropic account.
      </p>
      {st.configured ? (
        <>
          <p>
            <span className="good">●</span> API key saved ({st.key_hint}) · model {st.model}
          </p>
          {st.state === "error" && st.error && <p className="warn">Last debrief failed: {st.error}</p>}
          <Field label="Write a debrief automatically when a session ends">
            <input type="checkbox" checked={!!st.auto} disabled={busy} onChange={(e) => post({ auto: e.target.checked })} />
          </Field>
          <Field label="Replace the key">
            <input className="textin" type="password" value={key} placeholder="sk-ant-…" onChange={(e) => setKey(e.target.value)} />
          </Field>
          <div className="row">
            <button className="btn" disabled={busy || !key} onClick={() => post({ api_key: key })}>{busy ? "Checking…" : "Save key"}</button>
            <button className="btn btn--ghost" disabled={busy} onClick={() => confirm("Remove the API key from this PC?") && post({ clear: true })}>
              Remove key
            </button>
          </div>
        </>
      ) : (
        <>
          <Field label="Anthropic API key" hint="Create one at console.anthropic.com → API Keys (and add some credit under Billing). It's checked, then kept on this PC only.">
            <input className="textin" type="password" value={key} placeholder="sk-ant-…" onChange={(e) => setKey(e.target.value)} />
          </Field>
          <div className="row">
            <button className="btn" disabled={busy || !key} onClick={() => post({ api_key: key })}>{busy ? "Checking…" : "Save key"}</button>
          </div>
        </>
      )}
      {err && <p className="warn">{err}</p>}
    </div>
  );
}

type EditProps = { draft: Config; edit: (fn: (c: Config) => void) => void };

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  );
}

function General({ draft, edit }: EditProps) {
  return (
    <div className="panel">
      <Field label="Game" hint="Which game the rig service reads. Takes effect when the service restarts.">
        <select value={draft.game} onChange={(e) => edit((c) => (c.game = e.target.value as Config["game"]))}>
          <option value="ac">Assetto Corsa</option>
          <option value="demo">Demo (fake car, no game needed)</option>
        </select>
      </Field>
      <Field
        label="Assetto Corsa folder"
        hint="Leave empty to find it through Steam. Otherwise the folder that contains “content\\tracks”."
      >
        <input
          className="textin"
          placeholder="found automatically"
          value={draft.games.ac.install_dir}
          onChange={(e) => edit((c) => (c.games.ac.install_dir = e.target.value.trim()))}
        />
      </Field>
      <Field label="Accent colour">
        <input type="color" value={draft.display.accent} onChange={(e) => edit((c) => (c.display.accent = e.target.value))} />
      </Field>
      <Field label="Break reminder" hint="Minutes of driving before a gentle reminder. 0 = off.">
        <input
          type="number"
          min={0}
          max={600}
          value={draft.session_timer.break_reminder_min}
          onChange={(e) => edit((c) => (c.session_timer.break_reminder_min = Number(e.target.value)))}
        />
      </Field>
      <h2>Vertical monitor</h2>
      <Field label="Open the dashboard automatically" hint="Starts Chrome (or Edge) full-screen on the vertical monitor when the service starts.">
        <input
          type="checkbox"
          checked={draft.display.open_browser}
          onChange={(e) => edit((c) => (c.display.open_browser = e.target.checked))}
        />
      </Field>
      <MonitorPicker draft={draft} edit={edit} />
      <Field label="Browser">
        <select value={draft.display.browser} onChange={(e) => edit((c) => (c.display.browser = e.target.value as Config["display"]["browser"]))}>
          <option value="auto">Auto (Chrome, then Edge)</option>
          <option value="edge">Edge</option>
          <option value="chrome">Chrome</option>
        </select>
      </Field>

      <Field
        label="Braking points from"
        hint="Where “brake in” counts down to, here and in the game. The optimal run is the car at its grip on the optimal line: where to get to. Until it's worked out (a few clean laps), your best lap is used."
      >
        <select value={draft.coach.brake_cue} onChange={(e) => edit((c) => (c.coach.brake_cue = e.target.value as Config["coach"]["brake_cue"]))}>
          <option value="optimal">The optimal run (push yourself)</option>
          <option value="best">Your best lap</option>
        </select>
      </Field>

      <h2>In-game overlay</h2>
      <p className="field__hint">
        Pitwall's app inside Assetto Corsa: open it from the app bar and leave it open. It stays invisible until a
        braking point is coming up. Changes apply in the game straight away.
      </p>
      <Field label="Show the turn" hint="An arrow bent the way the corner goes (tighter for sharper corners), with the gear to be in underneath.">
        <input type="checkbox" checked={draft.overlay.show_turn} onChange={(e) => edit((c) => (c.overlay.show_turn = e.target.checked))} />
      </Field>
      <Field label="Show the corner's name" hint="In small text under the gear.">
        <input
          type="checkbox"
          checked={draft.overlay.show_turn_name}
          disabled={!draft.overlay.show_turn}
          onChange={(e) => edit((c) => (c.overlay.show_turn_name = e.target.checked))}
        />
      </Field>
      <Field label="Show the braking point" hint="A countdown bar that turns into BRAKE at the point. Adjusts to how fast you're arriving.">
        <input type="checkbox" checked={draft.overlay.show_brake} onChange={(e) => edit((c) => (c.overlay.show_brake = e.target.checked))} />
      </Field>
      <Field label="Appear this far before braking (m)">
        <input
          type="number"
          min={100}
          max={600}
          step={10}
          value={draft.overlay.show_from_m}
          onChange={(e) => edit((c) => (c.overlay.show_from_m = Number(e.target.value)))}
        />
      </Field>
    </div>
  );
}

interface Mon {
  x: number;
  y: number;
  width: number;
  height: number;
  primary: boolean;
  portrait: boolean;
}

function MonitorPicker({ draft, edit }: EditProps) {
  const [mons, setMons] = useState<{ monitors: Mon[]; auto: Mon | null } | null>(null);
  useEffect(() => {
    fetch("/api/monitors")
      .then((r) => r.json())
      .then(setMons, () => setMons(null));
  }, []);
  const manual = draft.display.monitor === "manual";
  const label = (m: Mon) =>
    `${m.width}×${m.height}${m.portrait ? " (vertical)" : ""}${m.primary ? " · main screen" : ""}`;
  return (
    <>
      <Field
        label="Which monitor"
        hint={
          manual
            ? "Pitwall opens at the position below."
            : mons?.auto
              ? `Auto: opens on the ${label(mons.auto)} monitor.`
              : "Auto: picks your vertical monitor (or any second screen)."
        }
      >
        <select
          value={manual ? `${draft.display.window_x},${draft.display.window_y}` : "auto"}
          onChange={(e) =>
            edit((c) => {
              if (e.target.value === "auto") {
                c.display.monitor = "auto";
              } else {
                const [x, y] = e.target.value.split(",").map(Number);
                c.display.monitor = "manual";
                c.display.window_x = x;
                c.display.window_y = y;
              }
            })
          }
        >
          <option value="auto">Auto (recommended)</option>
          {mons?.monitors.map((m) => (
            <option key={`${m.x},${m.y}`} value={`${m.x},${m.y}`}>
              {label(m)}
            </option>
          ))}
          {manual && !mons?.monitors.some((m) => m.x === draft.display.window_x && m.y === draft.display.window_y) && (
            <option value={`${draft.display.window_x},${draft.display.window_y}`}>
              Custom ({draft.display.window_x}, {draft.display.window_y})
            </option>
          )}
        </select>
      </Field>
    </>
  );
}

function Layout({ draft, edit }: EditProps) {
  const modes = [
    ["driving", "Driving (on track)"],
    ["analysis", "Analysis (pits, menus, replays)"],
  ] as const;
  return (
    <div className="panel">
      <p className="muted">
        Each mode has pages; switch pages with a wheel button. Widgets stack top to bottom; size is each one's share of the
        height.
      </p>
      {modes.map(([mode, label]) => (
        <div key={mode} className="layout">
          <h2>{label}</h2>
          {draft.layouts[mode].map((page, pi) => (
            <div key={pi} className="layout__page">
              <div className="layout__pagehead">
                <span>Page {pi + 1}</span>
                {draft.layouts[mode].length > 1 && (
                  <button className="btn btn--ghost btn--sm" onClick={() => edit((c) => c.layouts[mode].splice(pi, 1))}>
                    Remove page
                  </button>
                )}
              </div>
              <div className="layout__body">
                <ol className="layout__list">
                  {page.map((slot, si) => (
                    <SlotRow
                      key={si}
                      slot={slot}
                      first={si === 0}
                      last={si === page.length - 1}
                      onMove={(d) =>
                        edit((c) => {
                          const arr = c.layouts[mode][pi];
                          const [s] = arr.splice(si, 1);
                          arr.splice(si + d, 0, s);
                        })
                      }
                      onSize={(n) => edit((c) => (c.layouts[mode][pi][si].size = n))}
                      onRemove={() => edit((c) => c.layouts[mode][pi].splice(si, 1))}
                    />
                  ))}
                </ol>
                <Preview page={page} />
              </div>
              <AddWidget onAdd={(w) => edit((c) => c.layouts[mode][pi].push({ widget: w, size: 2 }))} />
            </div>
          ))}
          <button className="btn btn--ghost" onClick={() => edit((c) => c.layouts[mode].push([{ widget: "lap_times", size: 3 }]))}>
            + Add page
          </button>
        </div>
      ))}
    </div>
  );
}

function SlotRow(props: {
  slot: WidgetSlot;
  first: boolean;
  last: boolean;
  onMove: (d: number) => void;
  onSize: (n: number) => void;
  onRemove: () => void;
}) {
  const { slot } = props;
  return (
    <li className="slot">
      <span className="slot__name">{WIDGETS[slot.widget]?.label ?? slot.widget}</span>
      <span className="slot__size">
        <button className="btn btn--sm btn--ghost" onClick={() => props.onSize(Math.max(1, slot.size - 1))} aria-label="Smaller">
          −
        </button>
        <b>{slot.size}</b>
        <button className="btn btn--sm btn--ghost" onClick={() => props.onSize(Math.min(12, slot.size + 1))} aria-label="Bigger">
          +
        </button>
      </span>
      <button className="btn btn--sm btn--ghost" disabled={props.first} onClick={() => props.onMove(-1)} aria-label="Move up">
        ↑
      </button>
      <button className="btn btn--sm btn--ghost" disabled={props.last} onClick={() => props.onMove(1)} aria-label="Move down">
        ↓
      </button>
      <button className="btn btn--sm btn--ghost" onClick={props.onRemove} aria-label="Remove">
        ✕
      </button>
    </li>
  );
}

function Preview({ page }: { page: WidgetSlot[] }) {
  return (
    <div className="preview" aria-hidden>
      {page.map((s, i) => (
        <div key={i} className="preview__slot" style={{ flexGrow: s.size }}>
          {WIDGETS[s.widget]?.label}
        </div>
      ))}
    </div>
  );
}

function AddWidget({ onAdd }: { onAdd: (w: WidgetId) => void }) {
  return (
    <select
      className="addw"
      value=""
      onChange={(e) => {
        if (e.target.value) onAdd(e.target.value as WidgetId);
      }}
    >
      <option value="">+ Add widget…</option>
      {Object.entries(WIDGETS).map(([id, w]) => (
        <option key={id} value={id}>
          {w.label}
        </option>
      ))}
    </select>
  );
}

const KEY_NAMES: Record<string, string> = { right: "→", left: "←", up: "↑", down: "↓", cmd: "Win" };

/** "<ctrl>+<alt>+<right>" -> "Ctrl + Alt + →" */
export function prettyCombo(combo: string): string {
  return combo
    .split("+")
    .map((k) => k.replace(/[<>]/g, ""))
    .map((k) => KEY_NAMES[k] ?? (k.length === 1 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1)))
    .join(" + ");
}

function describe(b: Binding): string {
  if (b.type === "key") return `Key ${prettyCombo(b.combo)}`;
  if (b.type === "button") return `${b.device_name} · button ${b.index + 1}`;
  return `${b.device_name} · axis ${b.index + 1} ${b.direction === -1 ? "−" : "+"}`;
}

function Controls({
  draft,
  edit,
  actions,
  bindingAction,
  dirty,
}: EditProps & { actions: Record<string, string>; bindingAction: string | null; dirty: boolean }) {
  const [devices, setDevices] = useState<Awaited<ReturnType<typeof inputDevices>> | null>(null);
  useEffect(() => {
    inputDevices().then(setDevices, () => setDevices(null));
  }, []);
  const [wizard, setWizard] = useState(false);
  return (
    <div className="panel">
      {wizard ? (
        <BindWizard bindingAction={bindingAction} onDone={() => setWizard(false)} />
      ) : (
        <div className="wizcta">
          <div>
            <b>New here?</b> Bind the most useful actions one by one — press a wheel button for each, or skip it.
          </div>
          <button className="btn" disabled={dirty} onClick={() => setWizard(true)}>
            Set up recommended controls
          </button>
        </div>
      )}
      <p className="muted">
        Bind SF1000 buttons, encoders or a clutch paddle. Keyboard shortcuts work even while the game has focus — handy for
        the rim without spare buttons.
      </p>
      {devices && (
        <p className="muted">
          Wheel input: {devices.joystick ? `on (${devices.devices.map((d) => d.name).join(", ") || "no devices found"})` : "off — install the input extras on the rig PC"}
          {" · "}Keyboard shortcuts: {devices.keyboard ? "on" : "off"}
        </p>
      )}
      <div className="row">
        <Field
          label="Time Shift rewind key"
          hint="Pitwall holds this key while you hold your Rewind button (Time Shift rewinds while it's held). Bind the same key inside CSP's Time Shift app."
        >
          <input
            className="textin"
            value={draft.games.ac.rewind_key}
            onChange={(e) => edit((c) => (c.games.ac.rewind_key = e.target.value.trim()))}
          />
        </Field>
        <Field
          label="Drill run-up (seconds)"
          hint="A drill retry rewinds to this much driving before the section starts, so you've got a moment to settle in."
        >
          <input
            className="textin"
            type="number"
            min={0}
            max={15}
            step={0.5}
            value={draft.drills.lead_in_s}
            onChange={(e) => edit((c) => (c.drills.lead_in_s = Number(e.target.value)))}
          />
        </Field>

      </div>
      {dirty && <p className="warn">Save your other changes before binding buttons.</p>}
      {Object.entries(actions).map(([action, label]) => {
        const binds = draft.bindings[action] ?? [];
        const waiting = bindingAction === action;
        return (
          <Fragment key={action}>
          <div className="bind">
            <div className="bind__label">{label}</div>
            <ul className="bind__list">
              {binds.map((b, i) => (
                <li key={i}>
                  {describe(b)}
                  <button
                    className="btn btn--sm btn--ghost"
                    onClick={() => edit((c) => c.bindings[action].splice(i, 1))}
                    aria-label="Remove binding"
                  >
                    ✕
                  </button>
                </li>
              ))}
              {binds.length === 0 && <li className="muted">Not bound</li>}
            </ul>
            <div className="bind__buttons">
              {waiting ? (
                <>
                  <span className="pulse">Press a button or pull a paddle…</span>
                  <button className="btn btn--ghost btn--sm" onClick={() => cancelBinding()}>
                    Cancel
                  </button>
                </>
              ) : (
                <button className="btn btn--sm" disabled={dirty} onClick={() => startBinding(action)}>
                  Bind wheel / pedal
                </button>
              )}
              <KeyAdder
                onAdd={(combo) =>
                  edit((c) => {
                    c.bindings[action] = [...(c.bindings[action] ?? []), { type: "key", combo }];
                  })
                }
              />
            </div>
          </div>
          </Fragment>
        );
      })}
    </div>
  );
}

const RECOMMENDED: { action: string; title: string; why: string }[] = [
  {
    action: "rewind",
    title: "Rewind",
    why: "Hold to rewind with Time Shift, let go to drive on. During a drill, one press takes you back to just before the section. A thumb button.",
  },
  { action: "drill_here", title: "Drill the next corner", why: "Start practising the corner you're approaching, without touching the mouse." },
  { action: "stop_drill", title: "Stop the drill", why: "Back to normal laps." },
  { action: "next_page", title: "Next dashboard page", why: "Flip between the driving pages. An encoder click or a spare button." },
  { action: "open_analysis", title: "Open analysis on the main screen", why: "For when you pull into the pits." },
  { action: "mark_corner", title: "Mark this spot", why: "Drop a marker where something felt wrong, to look at later." },
];

/** Steps through RECOMMENDED, waiting for a wheel press on each (or a skip). */
function BindWizard({ bindingAction, onDone }: { bindingAction: string | null; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [waiting, setWaiting] = useState(false);
  const [armed, setArmed] = useState(false);
  const item = RECOMMENDED[step];

  useEffect(() => {
    if (!item) return;
    startBinding(item.action).then(() => setWaiting(true));
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps
  // The rig sets bindingAction to this action, then clears it once a press
  // has been captured: only then move on.
  useEffect(() => {
    if (!waiting || !item) return;
    if (bindingAction === item.action) setArmed(true);
    else if (bindingAction === null && armed) {
      setWaiting(false);
      setArmed(false);
      setStep((s) => s + 1);
    }
  }, [bindingAction, waiting, armed, item]);

  if (!item) {
    return (
      <div className="wiz">
        <h3>All set ✓</h3>
        <p className="muted">You can change any of these below, or add keyboard shortcuts.</p>
        <button className="btn" onClick={onDone}>
          Done
        </button>
      </div>
    );
  }
  return (
    <div className="wiz">
      <div className="wiz__step">
        Step {step + 1} of {RECOMMENDED.length}
      </div>
      <h3>{item.title}</h3>
      <p className="muted">{item.why}</p>
      <p className="pulse">Press the wheel button you want for this…</p>
      <div className="row">
        <button
          className="btn btn--ghost"
          onClick={async () => {
            await cancelBinding();
            setWaiting(false);
            setArmed(false);
            setStep((s) => s + 1);
          }}
        >
          Skip
        </button>
        <button
          className="btn btn--ghost"
          onClick={async () => {
            await cancelBinding();
            onDone();
          }}
        >
          Stop
        </button>
      </div>
    </div>
  );
}

function KeyAdder({ onAdd }: { onAdd: (combo: string) => void }) {
  const [v, setV] = useState("");
  return (
    <span className="keyadd">
      <input placeholder="<ctrl>+<alt>+n" value={v} onChange={(e) => setV(e.target.value)} />
      <button
        className="btn btn--sm btn--ghost"
        disabled={!v.trim()}
        onClick={() => {
          onAdd(v.trim());
          setV("");
        }}
      >
        Add key
      </button>
    </span>
  );
}

function Advanced({ draft, edit, onReset }: EditProps & { onReset: () => void }) {
  return (
    <div className="panel">
      <div className="row">
        <Field label="Telemetry poll rate (Hz)">
          <input type="number" min={1} max={120} value={draft.rates.poll_hz} onChange={(e) => edit((c) => (c.rates.poll_hz = Number(e.target.value)))} />
        </Field>
        <Field label="Dashboard update rate (Hz)">
          <input
            type="number"
            min={1}
            max={120}
            value={draft.rates.broadcast_hz}
            onChange={(e) => edit((c) => (c.rates.broadcast_hz = Number(e.target.value)))}
          />
        </Field>
      </div>
      <Field label="Wheels off track before a lap is invalid" hint="Assetto Corsa's rule: more than 2.">
        <input
          type="number"
          min={0}
          max={4}
          value={draft.laps.max_tyres_out}
          onChange={(e) => edit((c) => (c.laps.max_tyres_out = Number(e.target.value)))}
        />
      </Field>
      <Field label="Port" hint="Takes effect when the service restarts.">
        <input type="number" value={draft.server.port} onChange={(e) => edit((c) => (c.server.port = Number(e.target.value)))} />
      </Field>
      <button className="btn btn--danger" onClick={onReset}>
        Reset all settings
      </button>
    </div>
  );
}
