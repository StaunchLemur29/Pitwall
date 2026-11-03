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
};

type Listener = () => void;
type ActionListener = (action: string) => void;

class RigStore {
  state: RigState = initial;
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
        const { type: _t, ...live } = e;
        this.set({ live });
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
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  get = (): RigState => this.state;
}

export const rig = new RigStore();

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

export async function startDrill(body: { corner: number } | { start_p: number; end_p: number; name: string }): Promise<string[]> {
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
