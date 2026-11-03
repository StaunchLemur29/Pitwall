// Connection to the rig service: one WebSocket, one store, React hooks on top.

import { useSyncExternalStore } from "react";
import type {
  Attempt,
  Capabilities,
  Config,
  CornerReport,
  TrackGeometry,
  LapSummary,
  Live,
  Marker,
  Mode,
  ServerEvent,
  SessionInfo,
} from "./types";

export interface RigState {
  connected: boolean;
  config: Config | null;
  actions: Record<string, string>;
  capabilities: Capabilities | null;
  game: string;
  session: SessionInfo | null;
  mode: Mode;
  startedAt: number;
  live: Live;
  laps: LapSummary[];
  outline: [number, number, number][];
  markers: Marker[];
  lastLap: { lap: LapSummary; newBest: boolean; at: number } | null;
  bindingAction: string | null;
  track: TrackGeometry | null;
  corners: CornerReport | null;
  refTrace: Record<string, number[]> | null;
  lastAttempt: (Attempt & { at: number }) | null;
  stopped: boolean;
  retry: { state: string; at: number } | null;
}

const initial: RigState = {
  connected: false,
  config: null,
  actions: {},
  capabilities: null,
  game: "",
  session: null,
  mode: "idle",
  startedAt: Date.now() / 1000,
  live: { frame: null, delta_s: null, ref_lap_ms: null, theoretical_best_ms: null, driving_s: 0, track: null },
  laps: [],
  outline: [],
  markers: [],
  lastLap: null,
  bindingAction: null,
  track: null,
  corners: null,
  refTrace: null,
  lastAttempt: null,
  stopped: false,
  retry: null,
};

type Listener = () => void;
type ActionListener = (action: string) => void;

/** How often the general dashboard redraws with live data (the road view runs at full rate). */
const LIVE_UI_HZ = 15;

class RigStore {
  state: RigState = initial;
  latest: Live | null = null;
  private lastLiveSet = 0;
  private liveTimer = 0;
  private frameListeners = new Set<(l: Live) => void>();

  /** Every telemetry frame, without causing React redraws. */
  onFrame(fn: (l: Live) => void): () => void {
    this.frameListeners.add(fn);
    return () => this.frameListeners.delete(fn);
  }
  private listeners = new Set<Listener>();
  private actionListeners = new Set<ActionListener>();
  private ws: WebSocket | null = null;
  private retry = 0;

  connect(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.set({ connected: true });
    };
    ws.onmessage = (ev) => this.handle(JSON.parse(ev.data) as ServerEvent);
    ws.onclose = () => {
      this.set({ connected: false });
      const wait = Math.min(5000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), wait);
    };
  }

  send(obj: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  action(name: string): void {
    this.send({ type: "action", action: name });
  }

  onAction(fn: ActionListener): () => void {
    this.actionListeners.add(fn);
    return () => this.actionListeners.delete(fn);
  }

  private handle(e: ServerEvent): void {
    switch (e.type) {
      case "frame": {
        const { type: _t, ts, tick_hz, game_hz, ...live } = e;
        lag.record(Date.now() - ts * 1000, tick_hz, game_hz);
        // Full-rate consumers (road view, gauge) get every frame directly…
        this.latest = live;
        this.frameListeners.forEach((fn) => fn(live));
        // …the rest of the dashboard redraws at most LIVE_UI_HZ times a second.
        const now = performance.now();
        if (now - this.lastLiveSet >= 1000 / LIVE_UI_HZ) {
          this.lastLiveSet = now;
          this.set({ live });
        } else if (!this.liveTimer) {
          this.liveTimer = window.setTimeout(() => {
            this.liveTimer = 0;
            this.lastLiveSet = performance.now();
            this.set({ live: this.latest! });
          }, 1000 / LIVE_UI_HZ - (now - this.lastLiveSet));
        }
        break;
      }
      case "hello":
        this.set({
          config: e.config,
          actions: e.actions,
          capabilities: e.capabilities,
          game: e.game,
          session: e.session,
          mode: e.mode,
          startedAt: e.started_at,
          laps: e.recent_laps,
          track: e.track,
        });
        if (e.corners) this.setCorners(e.corners);
        break;
      case "track":
        this.set({ track: e.track });
        break;
      case "corners": {
        const { type: _t, ...report } = e;
        this.setCorners(report);
        break;
      }
      case "attempt":
        this.set({ lastAttempt: { ...e.attempt, at: Date.now() } });
        break;
      case "drill":
        break;
      case "retry":
        this.set({ retry: { state: e.state, at: Date.now() } });
        break;
      case "shutdown":
        this.set({ stopped: true });
        break;
      case "session":
        this.set({ session: e.session, laps: [], outline: [], markers: [] });
        void this.refreshOutline();
        void this.refreshLaps();
        break;
      case "mode":
        this.set({ mode: e.mode });
        break;
      case "lap":
        this.set({
          laps: [e.lap, ...this.state.laps].slice(0, 100),
          lastLap: { lap: e.lap, newBest: e.new_best, at: Date.now() },
        });
        if (this.state.outline.length === 0 || e.new_best) void this.refreshOutline();
        break;
      case "outline":
        this.set({ outline: e.points, markers: e.markers });
        break;
      case "markers":
        this.set({ markers: e.markers });
        break;
      case "config":
        this.set({ config: e.config });
        break;
      case "binding":
        this.set({ bindingAction: e.action });
        break;
      case "bound":
        this.set({ bindingAction: null });
        break;
      case "action":
        this.actionListeners.forEach((fn) => fn(e.action));
        break;
    }
  }

  private refId: number | null = null;

  private setCorners(report: CornerReport): void {
    this.set({ corners: report });
    const id = report.reference_lap_id;
    if (id !== this.refId) {
      this.refId = id;
      if (id === null) this.set({ refTrace: null });
      else
        fetch(`/api/laps/${id}/trace?hz=10`)
          .then((r) => (r.ok ? r.json() : null))
          .then((tr) => this.set({ refTrace: tr }));
    }
  }

  async refreshOutline(): Promise<void> {
    const r = await fetch("/api/track/outline");
    if (r.ok) {
      const d = await r.json();
      this.set({ outline: d.points, markers: d.markers });
    }
  }

  async refreshLaps(): Promise<void> {
    const r = await fetch("/api/laps?current=1&limit=100");
    if (r.ok) this.set({ laps: await r.json() });
  }

  private set(patch: Partial<RigState>): void {
    perf.storeUpdates++;
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  get = (): RigState => this.state;
}

/** Numbers for the lag meter: how old data is when it arrives, and how often. */
class LagStats {
  ages: number[] = [];
  arrivals: number[] = [];
  tickHz = 0;
  gameHz = 0;

  record(ageMs: number, tickHz: number, gameHz: number): void {
    const now = performance.now();
    this.ages.push(ageMs);
    this.arrivals.push(now);
    while (this.arrivals.length && now - this.arrivals[0] > 2000) {
      this.arrivals.shift();
      this.ages.shift();
    }
    this.tickHz = tickHz;
    this.gameHz = gameHz;
  }

  summary() {
    const a = this.ages;
    const gaps = this.arrivals.slice(1).map((t, i) => t - this.arrivals[i]);
    return {
      msgsPerS: this.arrivals.length / 2,
      ageAvg: a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0,
      ageMax: a.length ? Math.max(...a) : 0,
      gapMax: gaps.length ? Math.max(...gaps) : 0,
      tickHz: this.tickHz,
      gameHz: this.gameHz,
    };
  }
}

export const lag = new LagStats();

/** Counters for the performance part of the lag meter. */
export const perf = { storeUpdates: 0, renders: 0 };

export const rig = new RigStore();

export async function minimizeWindow(which: "dashboard" | "analysis"): Promise<void> {
  await fetch(`/api/window/${which}/minimize`, { method: "POST" }).catch(() => undefined);
}

export async function stopPitwall(): Promise<void> {
  await fetch("/api/shutdown", { method: "POST" }).catch(() => undefined);
}

export async function closeWindow(which: "dashboard" | "analysis"): Promise<void> {
  try {
    window.close(); // works when the browser allows it
  } catch {
    /* ignore */
  }
  await fetch(`/api/window/${which}/close`, { method: "POST" }).catch(() => undefined);
}

export function useRig<T>(select: (s: RigState) => T): T {
  return useSyncExternalStore(rig.subscribe, () => select(rig.get()));
}

// -- REST helpers --------------------------------------------------------------

export async function saveConfig(cfg: Config): Promise<string[]> {
  const r = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (r.ok) return [];
  const body = await r.json().catch(() => ({ errors: [`HTTP ${r.status}`] }));
  return body.errors ?? [`HTTP ${r.status}`];
}

export async function resetConfig(): Promise<void> {
  await fetch("/api/config/reset", { method: "POST" });
}

export async function startBinding(action: string): Promise<void> {
  await fetch(`/api/bind/${encodeURIComponent(action)}`, { method: "POST" });
}

export async function cancelBinding(): Promise<void> {
  await fetch("/api/bind", { method: "DELETE" });
}

export async function startDrill(
  body: { corner: number } | { section: number } | { chapter: number } | { start_p: number; end_p: number; name: string },
): Promise<string[]> {
  const r = await fetch("/api/drill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.ok) return [];
  return (await r.json().catch(() => ({ errors: [`HTTP ${r.status}`] }))).errors;
}

export async function stopDrill(): Promise<void> {
  await fetch("/api/drill", { method: "DELETE" });
}

export async function fetchCorners(lapId: number | null): Promise<CornerReport> {
  return (await fetch(`/api/corners${lapId ? `?lap_id=${lapId}` : ""}`)).json();
}

export async function fetchTrace(lapId: number, hz = 10): Promise<Record<string, number[]> | null> {
  const r = await fetch(`/api/laps/${lapId}/trace?hz=${hz}`);
  return r.ok ? r.json() : null;
}

export async function inputDevices(): Promise<{
  joystick: boolean;
  keyboard: boolean;
  devices: { guid: string; name: string }[];
}> {
  return (await fetch("/api/input/devices")).json();
}
