import { useEffect, useRef } from "react";
import { rig, useRig } from "../lib/rig";
import { GRADE_COLORS } from "../lib/track";
import { Card } from "./common";

/** The corner you're approaching, readable at a glance. */
export function NextCorner() {
  const t = useRig((s) => s.live.track);
  const f = useRig((s) => s.live.frame);
  const hasTrack = useRig((s) => !!s.track);
  const c = t?.corner;

  if (!hasTrack || !c) {
    const pct = f ? Math.round(f.lap_progress * 100) : 0;
    return (
      <Card title="Next corner">
        <div className="nextc">
          <div className="nextc__main">
            {f && f.status !== "off" ? `${pct}%` : "—"}
            <span className="nextc__sub">{hasTrack ? "of the lap" : "corners appear once the track loads"}</span>
          </div>
        </div>
      </Card>
    );
  }

  const inCorner = c.distance_m === 0;
  const brakeIn = c.brake_in_m;
  const brakeSoon = brakeIn !== null && brakeIn < 250;
  const brakeNear = brakeIn !== null && brakeIn < 300; // shown only when it matters
  return (
    <Card
      title={inCorner ? "In corner" : <>Next · <LiveMetres field="distance_m" initial={c.distance_m} /> m</>}
      right={
        c.grade_mastery && c.grade_mastery !== "new" ? (
          <span className="mdot" style={{ background: GRADE_COLORS[c.grade_mastery] }} title={`Mastery: ${c.grade_mastery}`} />
        ) : null
      }
    >
      <div className="corner">
        <div className={`corner__sign corner__sign--${c.direction}`} aria-label={c.direction === "L" ? "Left" : "Right"}>
          <Arrow dir={c.direction} grade={c.grade} />
          <span className="corner__grade">
            {c.direction}
            {c.grade}
          </span>
        </div>
        <div className="corner__info">
          <div className="corner__name">{c.label}</div>
          <div className="corner__chips">
            {c.gear ? <span className="chip">Gear {c.gear}</span> : null}
            {c.apex_kmh ? <span className="chip">{Math.round(c.apex_kmh)} km/h</span> : null}
            {!c.gear && <span className="chip chip--dim">drive a clean lap for targets</span>}
          </div>
        </div>
      </div>
      <div className={`brakeslot ${brakeNear ? "" : "brakeslot--hidden"}`}>
        {brakeIn !== null && <BrakeBar initial={brakeIn} soon={brakeSoon} />}
      </div>
    </Card>
  );
}

/** A corner arrow whose bend gets tighter with lower (sharper) grades. */
function Arrow({ dir, grade }: { dir: "L" | "R"; grade: number }) {
  const bend = ([0, 170, 135, 105, 75, 50, 30][grade] ?? 60) * (Math.PI / 180);
  const s = dir === "R" ? 1 : -1;
  const r = grade <= 2 ? 16 : 24;
  const cx = 50 + s * r;
  const cy = 58;
  // Point and direction at the end of the arc.
  const ex = cx - s * r * Math.cos(bend);
  const ey = cy - r * Math.sin(bend);
  const tx = s * Math.sin(bend);
  const ty = -Math.cos(bend);
  const nx = -ty;
  const ny = tx;
  const tip = [ex + tx * 16, ey + ty * 16];
  const b1 = [ex + nx * 11, ey + ny * 11];
  const b2 = [ex - nx * 11, ey - ny * 11];
  return (
    <svg viewBox="0 0 100 100" className="corner__arrow">
      <path d={`M50,98 L50,${cy} A${r},${r} 0 0 ${s > 0 ? 1 : 0} ${ex.toFixed(1)},${ey.toFixed(1)}`} />
      <path className="corner__head" d={`M${tip.join(",")} L${b1.join(",")} L${b2.join(",")} Z`} />
    </svg>
  );
}

type CornerField = "distance_m" | "brake_in_m";

/**
 * Follows a corner distance every display frame: takes each telemetry update
 * as it arrives and counts down by the car's speed in between, writing straight
 * to the page (no React redraw), so the number and bar move smoothly.
 */
function useCountdown(field: CornerField, onValue: (m: number) => void) {
  const cb = useRef(onValue);
  cb.current = onValue;
  useEffect(() => {
    const s = { m: null as number | null, v: 0, at: 0 };
    const feed = () => {
      const lv = rig.latest;
      const m = lv?.track?.corner?.[field];
      const fresh = typeof m === "number" ? m : null;
      if (fresh !== s.m || fresh === null) {
        s.m = fresh;
        s.at = performance.now() - Math.max(0, Math.min(100, lv?.pos_age_ms ?? 0));
      }
      s.v = (lv?.frame?.speed_kmh ?? 0) / 3.6;
    };
    feed();
    const off = rig.onFrame(feed);
    let raf = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (s.m === null) return;
      const lead = Math.min(0.15, Math.max(0, (now - s.at) / 1000));
      cb.current(Math.max(0, s.m - s.v * lead));
    };
    raf = requestAnimationFrame(tick);
    return () => {
      off();
      cancelAnimationFrame(raf);
    };
  }, [field]);
}

function LiveMetres({ field, initial }: { field: CornerField; initial: number }) {
  const el = useRef<HTMLSpanElement>(null);
  useCountdown(field, (m) => {
    if (el.current) el.current.textContent = String(Math.round(m));
  });
  return <span ref={el}>{initial}</span>;
}

function BrakeBar({ initial, soon }: { initial: number; soon: boolean }) {
  const fill = useRef<HTMLDivElement>(null);
  const value = useRef<HTMLSpanElement>(null);
  const width = (m: number) => `${Math.max(0, Math.min(100, 100 - m / 3))}%`;
  const bar = useRef<HTMLDivElement>(null);
  const label = useRef<HTMLSpanElement>(null);
  useCountdown("brake_in_m", (m) => {
    // At the braking point: BRAKE, held briefly, instead of the cue vanishing.
    const now = m <= 0.5;
    if (value.current) value.current.textContent = now ? "BRAKE" : `${Math.round(m)} m`;
    if (label.current) label.current.style.visibility = now ? "hidden" : "visible";
    if (fill.current) fill.current.style.width = now ? "100%" : width(m);
    bar.current?.classList.toggle("brakebar--now", now);
  });
  return (
    <div ref={bar} className={`brakebar ${soon ? "brakebar--soon" : ""} ${initial <= 0 ? "brakebar--now" : ""}`}>
      <span ref={label} className="brakebar__label">Brake in</span>
      <span ref={value} className="brakebar__value">{initial <= 0 ? "BRAKE" : `${initial} m`}</span>
      <div className="brakebar__track">
        <div ref={fill} className="brakebar__fill" style={{ width: width(initial) }} />
      </div>
    </div>
  );
}
