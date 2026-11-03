// Fitting a track outline into a widget, rotated so its long side runs along
// the widget's long side (portrait monitor → most tracks stand upright).

export type Pt = [number, number];

export interface Fit {
  /** world (x, z) → screen (x, y) */
  project: (x: number, z: number) => Pt;
  angle: number;
}

/** Angle (radians) of the principal axis of a point cloud. */
export function principalAngle(points: Pt[]): number {
  const n = points.length;
  if (n < 2) return 0;
  let mx = 0;
  let my = 0;
  for (const [x, y] of points) {
    mx += x;
    my += y;
  }
  mx /= n;
  my /= n;
  let sxx = 0;
  let syy = 0;
  let sxy = 0;
  for (const [x, y] of points) {
    const dx = x - mx;
    const dy = y - my;
    sxx += dx * dx;
    syy += dy * dy;
    sxy += dx * dy;
  }
  return 0.5 * Math.atan2(2 * sxy, sxx - syy);
}

export function fitTrack(points: Pt[], width: number, height: number, pad = 16): Fit {
  if (points.length < 2) return { project: () => [width / 2, height / 2], angle: 0 };
  // Line the track's long axis up with the box's long side, then try other
  // rotations and only switch if one draws the track clearly (15%) bigger.
  const base = (height >= width ? Math.PI / 2 : 0) - principalAngle(points);
  const scaleAt = (angle: number) => {
    const b = bounds(points, angle);
    return Math.min((width - pad * 2) / b.w, (height - pad * 2) / b.h);
  };
  let best = { angle: base, scale: scaleAt(base) };
  const threshold = best.scale * 1.15;
  for (let k = 1; k < 36; k++) {
    const angle = base + (k * Math.PI) / 36;
    const scale = scaleAt(angle);
    if (scale > threshold && scale > best.scale) best = { angle, scale };
  }
  const { angle, scale } = best;
  const b = bounds(points, angle);
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const ox = (width - b.w * scale) / 2;
  const oy = (height - b.h * scale) / 2;
  return {
    angle,
    project: (x, z) => {
      const rx = x * cos - z * sin;
      const ry = x * sin + z * cos;
      return [ox + (rx - b.minX) * scale, oy + (ry - b.minY) * scale];
    },
  };
}

function bounds(points: Pt[], angle: number) {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, z] of points) {
    const rx = x * cos - z * sin;
    const ry = x * sin + z * cos;
    if (rx < minX) minX = rx;
    if (rx > maxX) maxX = rx;
    if (ry < minY) minY = ry;
    if (ry > maxY) maxY = ry;
  }
  return { minX, minY, w: Math.max(1e-6, maxX - minX), h: Math.max(1e-6, maxY - minY) };
}

export function toPath(pts: Pt[], closed = true): string {
  if (!pts.length) return "";
  const body = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  return closed ? `${body}Z` : body;
}
