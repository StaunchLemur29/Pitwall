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
  /** used a rewind after a mistake: a normal lap, but never a best one */
  rewound?: boolean;
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
  /** optimal racing line (smoothest path the edges allow), same points as center; empty without edges */
  optimal?: [number, number][];
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
  /** metres towards the inside of the corner vs the optimal line (negative = wider) */
  line?: { entry: number; apex: number; exit: number };
  /** the optimal run through this corner (same measures as yours) */
  opt?: OptimalCorner;
  /** what you did differently from the optimal run, biggest first */
  opt_notes?: string[];
}

export interface OptimalCorner {
  time_s: number;
  brake_m: number | null;
  entry_kmh: number | null;
  peak_brake: number | null;
  min_speed_kmh: number;
  throttle_m: number | null;
  exit_kmh: number | null;
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
  /** The optimal line driven at this car's grip (learnt from your fastest laps); rig only. */
  optimal?: { lap_s: number; laps_used: number; grip: Record<string, number> } | null;
  /** Battery and DRS use on this lap (cars that have them). */
  systems: Systems | null;
  /** e.g. ["ABS (12)", "TC (8)", "DRS", "ERS (4 deploy modes)"] */
  car_systems: string[];
}

export interface SystemsRun {
  start_p: number;
  end_p: number;
  metres: number;
  near: string;
}

export interface Systems {
  drs: { open_m: number; missed: SystemsRun[] } | null;
  battery: { start: number; end: number; min: number; empty: SystemsRun[] } | null;
  notes: string[];
}

/** An AI debrief of one session. */
export interface Debrief {
  game: string;
  car: string;
  track_key: string;
  session_start: number; // unix seconds
  created_at: number;
  model: string;
  body: string; // short Markdown
}

/** Which systems the current car has. */
export interface CarProfile {
  abs: boolean;
  abs_levels: number | null;
  tc: boolean;
  tc_levels: number | null;
  brake_bias: boolean;
  drs: boolean;
  battery: boolean;
  ers: boolean;
  deploy_modes: number | null;
  engine_brake_maps: number | null;
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
  | "status_line"
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
  overlay: { show_turn: boolean; show_turn_name: boolean; show_brake: boolean; show_from_m: number };
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

/** The car's systems as the in-game app reports them; each field only if the car has it. */
export interface Electronics {
  abs: number | null;
  abs_modes: number | null;
  tc: number | null;
  tc_modes: number | null;
  bb: number | null;
  drs_present?: boolean | null;
  drs_available?: boolean | null;
  drs_active?: boolean | null;
  kers_present?: boolean | null;
  kers_charge?: number | null; // 0..1
  mguk_delivery?: number | null;
  mguk_delivery_count?: number | null;
  mguk_recovery?: number | null;
  engine_brake?: number | null;
  engine_brake_count?: number | null;
  fuel_map?: number | null;
}

export interface Live {
  frame: Frame | null;
  /** How old the car position was when this update was sent (ms), if known. */
  pos_age_ms?: number | null;
  /** Real ABS / TC levels and brake bias from the in-game CSP app (null without it). */
  electronics?: Electronics | null;
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
      car_profile: CarProfile | null;
      car_systems: string[];
    }
  | { type: "car_profile"; car_profile: CarProfile; summary: string[] }
  | { type: "notice"; text: string }
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
