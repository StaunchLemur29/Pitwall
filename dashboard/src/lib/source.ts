/**
 * Where the analysis screens get their data. On the rig PC that's the local
 * Pitwall service (live session, drills); in the hub it's Supabase (your
 * uploaded laps, read-only). The screens are the same either way.
 */
import { createContext, useContext } from "react";
import type { Trace } from "./profile";
import { fetchCombos, fetchCorners, fetchGeometry, fetchLaps, fetchOptimal, fetchTrace, type Combo } from "./rig";
import type { BlindSpot, CornerReport, Debrief, LapSummary, TrackGeometry } from "./types";

export interface AnalysisSource {
  /** A game session can be running here (live laps, drills, the analysis window). */
  live: boolean;
  combos(): Promise<Combo[]>;
  geometry(combo: Combo): Promise<TrackGeometry | null>;
  laps(combo: Combo): Promise<LapSummary[]>;
  /** One lap broken down, compared with another (null: the lap's best / next best). */
  corners(lapId: number | null, compareId: number | null, combo: Combo | null): Promise<CornerReport>;
  trace(lapId: number, hz: number): Promise<Trace | null>;
  /** The optimal run (optimal line at this car's grip) as a trace; null where there isn't one. */
  optimal(combo: Combo | null): Promise<{ lap_s: number; trace: Trace } | null>;
  /** AI debriefs for this car + track, newest first. */
  debriefs(combo: Combo): Promise<Debrief[]>;
  /** Habits your recent laps here show (rig PC only). */
  blindSpots?(combo: Combo | null): Promise<{ findings: BlindSpot[]; laps: number }>;
  /** Write one now (rig PC only, with an API key set). */
  writeDebrief?(combo: Combo): Promise<Debrief>;
  /** Whether debriefs can be written here (an API key is set). */
  canWriteDebrief?(): Promise<boolean>;
}

const q = (c: Combo) => new URLSearchParams({ game: c.game, car: c.car, track_key: c.track_key });

export const rigSource: AnalysisSource = {
  live: true,
  combos: fetchCombos,
  geometry: fetchGeometry,
  laps: fetchLaps,
  corners: fetchCorners,
  trace: fetchTrace,
  optimal: fetchOptimal,
  debriefs: async (c) => {
    const r = await fetch(`/api/debriefs?${q(c)}`);
    return r.ok ? r.json() : [];
  },
  blindSpots: async (c) => {
    const r = await fetch(`/api/blindspots${c ? `?${q(c)}` : ""}`);
    return r.ok ? r.json() : { findings: [], laps: 0 };
  },
  writeDebrief: async (c) => {
    const r = await fetch("/api/debrief", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game: c.game, car: c.car, track_key: c.track_key }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error ?? "Couldn't write the debrief");
    return j;
  },
  canWriteDebrief: async () => {
    const r = await fetch("/api/ai");
    return r.ok ? !!(await r.json()).configured : false;
  },
};

export const SourceContext = createContext<AnalysisSource>(rigSource);
export const useSource = () => useContext(SourceContext);
