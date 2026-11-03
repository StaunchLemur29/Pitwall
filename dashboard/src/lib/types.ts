// Mirrors the rig service's wire format (rig/src/pitwall_rig/models.py).

export type GameStatus = "off" | "replay" | "live" | "paused";
export type Mode = "driving" | "analysis" | "idle";

export interface Frame {
  t: number;
  status: GameStatus;
  packet_id: number;
  gas: number;
  brake: number;
  clutch: number;
  steer: number;
  speed_kmh: number;
  gear: number;
  rpm: number;
  fuel_l: number;
  brake_bias: number | null;
  abs: number | null;
  tc: number | null;
  abs_active: boolean;
  tc_active: boolean;
  tyre_pressure_psi: number[] | null;
  tyre_core_temp_c: number[] | null;
  tyres_out: number;
  lap: number;
  lap_time_ms: number;
  last_lap_ms: number;
  best_lap_ms: number;
  lap_progress: number;
  sector: number;
  in_pit_box: boolean;
  in_pit_lane: boolean;
  world: [number, number, number] | null;
  velocity: [number, number, number] | null;
  yaw: number | null;
  session_time_left_s: number | null;
  position: number;
}

export interface SessionInfo {
  game: string;
  car: string;
  track: string;
  track_config: string;
  track_key: string;
  session_type: string;
  track_length_m: number;
  max_rpm: number;
  max_fuel_l: number;
  sector_count: number;
  player_name: string;
}

export interface Capabilities {
  reports_brake_bias: boolean;
  reports_abs_level: boolean;
  reports_tc_level: boolean;
  reports_tyre_pressure: boolean;
  reports_world_position: boolean;
  can_retry_section: boolean;
}

export interface LapSummary {
  id: number;
  game: string;
  car: string;
  track_key: string;
  lap_number: number;
  lap_time_ms: number;
  valid: boolean;
  out_lap: boolean;
  started_at: number;
  sector_ms: number[];
}

export interface Marker {
  id: number;
  progress: number;
  x: number | null;
  z: number | null;
  note: string;
}

export interface Corner {
  number: number;
  name: string;
  label: string;
  direction: "L" | "R";
  grade: number;
  entry: number;
  apex: number;
  exit: number;
  apex_radius_m: number;
  apex_index: number;
}

export interface TrackGeometry {
  track_key: string;
  length_m: number;
  source: "game" | "laps";
  has_edges: boolean;
  progress: number[];
  center: [number, number][];
  left: [number, number][];
  right: [number, number][];
  corners: Corner[];
  sections: { name: string; start: number; end: number }[];
  chapters: Chapter[];
  practice: PracticeSection[];
}

export interface PracticeSection {
  number: number;
  name: string;
  corners: number[];
  start: number;
  end: number;
  time_s?: number | null;
  ref_s?: number | null;
  drill_best_s?: number | null;
}

export interface Chapter {
  number: number;
  name: string;
  summary: string;
  start: number;
  end: number;
  time_s?: number | null;
  ref_s?: number | null;
}

export interface CornerLive extends Corner {
  distance_m: number;
  brake_in_m: number | null;
  gear: number | null;
  apex_kmh: number | null;
  grade_mastery: Mastery["grade"] | null;
}

export interface Drill {
  name: string;
  start_p: number;
  end_p: number;
  corner: number | null;
  pass_within_s: number;
  pass_streak: number;
  best_ms: number | null;
  attempts: number;
  streak: number;
  passed: boolean;
  running: boolean;
  elapsed_s: number;
  last: Attempt | null;
  recent: Attempt[];
}

export interface Attempt {
  time_ms: number;
  clean: boolean;
  delta_s: number | null;
  counted: boolean;
}

export interface TrackLive {
  p: number;
  off_m: number | null;
  frac: number | null;
  heading: number;
  car_heading: number | null;
  corner?: CornerLive;
  drill?: Drill;
}

export interface Mastery {
  corner: number;
  best_s: number;
  median_s: number;
  spread_s: number | null;
  laps: number;
  grade: "new" | "green" | "amber" | "red";
}

export interface CornerLap {
  corner: number;
  time_s: number;
  min_speed_kmh: number;
  min_speed_p: number;
  apex_gear: number;
  brake_p: number | null;
  coast_s: number;
  entry_frac?: number;
  apex_frac?: number;
  exit_frac?: number;
  advice?: string[];
  loss_s?: number | null;
  /** metres before the apex braking started (null: no braking) */
  brake_m?: number | null;
  peak_brake?: number;
  entry_kmh?: number;
  exit_kmh?: number;
  /** metres after the apex you were back to full throttle (negative: before it) */
  throttle_m?: number | null;
  /** time through the corner minus the comparison lap's */
  vs_s?: number;
  /** what you did differently from the comparison lap, biggest first */
  notes?: string[];
}

export interface CornerReport {
  chapters: Chapter[];
  practice: PracticeSection[];
  mastery: Mastery[];
  lap_id: number | null;
  lap: CornerLap[] | null;
  reference: CornerLap[];
  reference_lap_id: number | null;
  compare: CornerLap[] | null;
  compare_lap_id: number | null;
  compare_label: string | null;
  /** which car + track this is, and whether it's the one you're driving now */
  game: string | null;
  car: string | null;
  track_key: string | null;
  live: boolean;
  theoretical_best_ms: number | null;
}

export type WidgetId =
  | "next_corner"
  | "turn_by_turn"
  | "lap_analysis"
  | "track_map"
  | "drill"
  | "coach_tip"
  | "electronics"
  | "lap_times"
  | "tyres"
  | "session_bar"
  | "recent_laps";

export interface WidgetSlot {
  widget: WidgetId;
  size: number;
}

export type Binding =
  | { type: "key"; combo: string }
  | {
      type: "button" | "axis";
      device: string;
      device_name: string;
      index: number;
      rest?: number;
      direction?: number;
    };

export interface Config {
  game: "ac" | "demo" | "replay";
  games: { ac: { install_dir: string; rewind_key: string } };
  drills: { lead_in_s: number };
  server: { host: string; port: number };
  rates: { poll_hz: number; broadcast_hz: number };
  laps: { max_tyres_out: number };
  units: { speed: string; pressure: string; temperature: string };
  display: {
    accent: string;
    open_browser: boolean;
    browser: "auto" | "edge" | "chrome";
    monitor: "auto" | "manual";
    window_x: number;
    window_y: number;
  };
  session_timer: { break_reminder_min: number };
  layouts: { driving: WidgetSlot[][]; analysis: WidgetSlot[][] };
  bindings: Record<string, Binding[]>;
}

export interface Live {
  frame: Frame | null;
  /** How old the car position was when this update was sent (ms), if known. */
  pos_age_ms?: number | null;
  delta_s: number | null;
  ref_lap_ms: number | null;
  theoretical_best_ms: number | null;
  driving_s: number;
  track: TrackLive | null;
}

export type ServerEvent =
  | ({ type: "frame"; ts: number; tick_hz: number; game_hz: number } & Live)
  | {
      type: "hello";
      config: Config;
      actions: Record<string, string>;
      capabilities: Capabilities;
      game: string;
      session: SessionInfo | null;
      mode: Mode;
      started_at: number;
      recent_laps: LapSummary[];
      track: TrackGeometry | null;
      corners: CornerReport | null;
      drill: Drill | null;
    }
  | { type: "session"; session: SessionInfo | null }
  | { type: "mode"; mode: Mode }
  | { type: "lap"; lap: LapSummary; new_best: boolean }
  | { type: "outline"; points: [number, number, number][]; markers: Marker[] }
  | { type: "markers"; markers: Marker[] }
  | { type: "action"; action: string }
  | { type: "config"; config: Config }
  | { type: "binding"; action: string }
  | { type: "bound"; action: string; binding: Binding }
  | { type: "track"; track: TrackGeometry | null }
  | ({ type: "corners" } & CornerReport)
  | { type: "drill"; drill: Drill | null }
  | { type: "shutdown" }
  | { type: "retry"; state: "rewinding" | "ready" | "no_rewind" | "timeout" | "stopped" }
  | { type: "attempt"; attempt: Attempt & { start_p: number; end_p: number } };
