import { useRig } from "../lib/rig";
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
  return (
    <Card
      title={inCorner ? "In corner" : `Next · ${c.distance_m} m`}
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
      {brakeIn !== null && !inCorner && (
        <div className={`brakebar ${brakeSoon ? "brakebar--soon" : ""}`}>
          <span className="brakebar__label">Brake in</span>
          <span className="brakebar__value">{brakeIn} m</span>
          <div className="brakebar__track">
            <div className="brakebar__fill" style={{ width: `${Math.max(0, Math.min(100, 100 - brakeIn / 3))}%` }} />
          </div>
        </div>
      )}
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
