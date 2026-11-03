import { describe, expect, it } from "vitest";
import { fitTrack, type Pt } from "./geometry";

describe("fitTrack", () => {
  // A long, thin horizontal oval: 1000 m wide, 100 m tall.
  const oval: Pt[] = Array.from({ length: 200 }, (_, i) => {
    const a = (i / 200) * Math.PI * 2;
    return [500 * Math.cos(a), 50 * Math.sin(a)];
  });

  it("stands a wide track upright in a portrait box", () => {
    const fit = fitTrack(oval, 400, 800, 0);
    const pts = oval.map(([x, z]) => fit.project(x, z));
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const w = Math.max(...xs) - Math.min(...xs);
    const h = Math.max(...ys) - Math.min(...ys);
    expect(h).toBeGreaterThan(w * 5);
    expect(Math.max(...ys)).toBeLessThanOrEqual(800.01);
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(-0.01);
  });

  it("keeps everything inside the padded box", () => {
    const fit = fitTrack(oval, 300, 300, 10);
    for (const [x, z] of oval) {
      const [sx, sy] = fit.project(x, z);
      expect(sx).toBeGreaterThanOrEqual(9.99);
      expect(sx).toBeLessThanOrEqual(290.01);
      expect(sy).toBeGreaterThanOrEqual(9.99);
      expect(sy).toBeLessThanOrEqual(290.01);
    }
  });
});
