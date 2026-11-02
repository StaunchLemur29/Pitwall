import { useEffect, useState } from "react";
import { cancelBinding, inputDevices, resetConfig, saveConfig, startBinding, useRig } from "../lib/rig";
import type { Binding, Config, WidgetId, WidgetSlot } from "../lib/types";
import { WIDGETS } from "../widgets";

type Tab = "general" | "layout" | "controls" | "advanced";

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
        {(["general", "layout", "controls", "advanced"] as Tab[]).map((t) => (
          <button key={t} className={`tabs__tab ${tab === t ? "tabs__tab--on" : ""}`} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      {tab === "general" && <General draft={draft} edit={edit} />}
      {tab === "layout" && <Layout draft={draft} edit={edit} />}
      {tab === "controls" && (
        <Controls draft={draft} edit={edit} actions={actions} bindingAction={bindingAction} dirty={dirty} />
      )}
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
      <Field label="Open the dashboard automatically" hint="Starts Edge/Chrome full-screen on the vertical monitor when the service starts.">
        <input
          type="checkbox"
          checked={draft.display.open_browser}
          onChange={(e) => edit((c) => (c.display.open_browser = e.target.checked))}
        />
      </Field>
      <div className="row">
        <Field label="Monitor left (px)" hint="Its left edge in Windows display settings. Main 1920 wide → 1920.">
          <input type="number" value={draft.display.window_x} onChange={(e) => edit((c) => (c.display.window_x = Number(e.target.value)))} />
        </Field>
        <Field label="Monitor top (px)">
          <input type="number" value={draft.display.window_y} onChange={(e) => edit((c) => (c.display.window_y = Number(e.target.value)))} />
        </Field>
      </div>
      <Field label="Browser">
        <select value={draft.display.browser} onChange={(e) => edit((c) => (c.display.browser = e.target.value as Config["display"]["browser"]))}>
          <option value="auto">Auto (Edge, then Chrome)</option>
          <option value="edge">Edge</option>
          <option value="chrome">Chrome</option>
        </select>
      </Field>
    </div>
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
  return (
    <div className="panel">
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
      {dirty && <p className="warn">Save your other changes before binding buttons.</p>}
      {Object.entries(actions).map(([action, label]) => {
        const binds = draft.bindings[action] ?? [];
        const waiting = bindingAction === action;
        return (
          <div key={action} className="bind">
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
        );
      })}
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
