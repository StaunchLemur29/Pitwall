/**
 * Where the analysis screens get their data. On the rig PC that's the local
 * Pitwall service (live session, drills); in the hub it's Supabase (your
 * uploaded laps, read-only). The screens are the same either way.
 */
import { createContext, useContext } from "react";
import type { Trace } from "./profile";
import { fetchCombos, fetchCorners, fetchGeometry, fetchLaps, fetchTrace, type Combo } from "./rig";
import type { CornerReport, LapSummary, TrackGeometry } from "./types";

export interface AnalysisSource {
  /** A game session can be running here (live laps, drills, the analysis window). */
  live: boolean;
  combos(): Promise<Combo[]>;
  geometry(combo: Combo): Promise<TrackGeometry | null>;
  laps(combo: Combo): Promise<LapSummary[]>;
  /** One lap broken down, compared with another (null: the lap's best / next best). */
  corners(lapId: number | null, compareId: number | null, combo: Combo | null): Promise<CornerReport>;
  trace(lapId: number, hz: number): Promise<Trace | null>;
}

export const rigSource: AnalysisSource = {
  live: true,
  combos: fetchCombos,
  geometry: fetchGeometry,
  laps: fetchLaps,
  corners: fetchCorners,
  trace: fetchTrace,
};

export const SourceContext = createContext<AnalysisSource>(rigSource);
export const useSource = () => useContext(SourceContext);
