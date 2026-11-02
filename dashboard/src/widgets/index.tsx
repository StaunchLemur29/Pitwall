import type { ComponentType } from "react";
import type { WidgetId } from "../lib/types";
import { Upcoming } from "./common";
import { Electronics } from "./Electronics";
import { LapTimes } from "./LapTimes";
import { NextCorner } from "./NextCorner";
import { RecentLaps } from "./RecentLaps";
import { SessionBar } from "./SessionBar";
import { TrackMap } from "./TrackMap";
import { Tyres } from "./Tyres";

export const WIDGETS: Record<WidgetId, { label: string; component: ComponentType }> = {
  next_corner: { label: "Next corner", component: NextCorner },
  track_map: { label: "Track map", component: TrackMap },
  drill: {
    label: "Drill / focus",
    component: () => (
      <Upcoming title="Drill" phase={1} note="Section drills with pass targets will show here." />
    ),
  },
  coach_tip: {
    label: "Coach tip",
    component: () => <Upcoming title="Coach" phase={3} note="One tip per lap, on a straight." />,
  },
  electronics: { label: "Electronics", component: Electronics },
  lap_times: { label: "Lap times & delta", component: LapTimes },
  tyres: { label: "Tyres", component: Tyres },
  session_bar: { label: "Session timer", component: SessionBar },
  recent_laps: { label: "Recent laps", component: RecentLaps },
};
