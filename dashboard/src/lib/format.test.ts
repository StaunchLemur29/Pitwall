import { describe, expect, it } from "vitest";
import { clock, delta, lapTime, prettyName } from "./format";

describe("format", () => {
  it("formats lap times", () => {
    expect(lapTime(83456)).toBe("1:23.456");
    expect(lapTime(425012)).toBe("7:05.012");
    expect(lapTime(0)).toBe("—");
  });

  it("formats deltas with explicit sign", () => {
    expect(delta(0.421)).toBe("+0.42");
    expect(delta(-1.07)).toBe("−1.07");
    expect(delta(0.001)).toBe("±0.00");
    expect(delta(null)).toBe("—");
  });

  it("formats clocks", () => {
    expect(clock(65)).toBe("1:05");
    expect(clock(3723)).toBe("1:02:03");
  });

  it("prettifies AC folder names", () => {
    expect(prettyName("ks_nordschleife@touristenfahrten")).toBe("Nordschleife · Touristenfahrten");
    expect(prettyName("rss_formula_hybrid_2021")).toBe("Formula Hybrid 2021");
    expect(prettyName("spa")).toBe("Spa");
  });
});
