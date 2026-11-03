import type { ComponentType } from "react";
import type { WidgetId } from "../lib/types";
import { Upcoming } from "./common";
import { DrillCard } from "./DrillCard";
import { Electronics } from "./Electronics";
import { LapAnalysis } from "./LapAnalysis";
import { LapTimes } from "./LapTimes";
import { NextCorner } from "./NextCorner";
import { RecentLaps } from "./RecentLaps";
import { SessionBar } from "./SessionBar";
import { StatusLine } from "./StatusLine";
import { TrackMap } from "./TrackMap";
import { TurnByTurn } from "./TurnByTurn";
import { Tyres } from "./Tyres";

export const WIDGETS: Record<WidgetId, { label: string; component: ComponentType }> = {
  next_corner: { label: "Next corner", component: NextCorner },
  turn_by_turn: { label: "Road ahead (turn-by-turn)", component: TurnByTurn },
  track_map: { label: "Track map", component: TrackMap },
  drill: { label: "Drill", component: DrillCard },
  coach_tip: {
    label: "Coach tip",
    component: () => <Upcoming title="Coach" phase={3} note="One tip per lap, on a straight." />,
  },
  electronics: { label: "Electronics", component: Electronics },
  lap_times: { label: "Lap times & delta", component: LapTimes },
  tyres: { label: "Tyres", component: Tyres },
  session_bar: { label: "Session timer", component: SessionBar },
  status_line: { label: "Status line", component: StatusLine },
  recent_laps: { label: "Recent laps", component: RecentLaps },
  lap_analysis: { label: "Lap analysis (map + corners)", component: LapAnalysis },
};
