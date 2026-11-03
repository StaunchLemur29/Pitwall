/** 83456 -> "1:23.456" */
export function lapTime(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return "—";
  const m = Math.floor(ms / 60000);
  const s = (ms % 60000) / 1000;
  return `${m}:${s.toFixed(3).padStart(6, "0")}`;
}

/** Seconds -> "+0.42" / "−1.07" (true minus sign for legibility). */
export function delta(s: number | null | undefined, digits = 2): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "—";
  const v = Math.abs(s).toFixed(digits);
  if (Number(v) === 0) return `±${v}`;
  return s < 0 ? `−${v}` : `+${v}`;
}

/** Seconds -> "1:02:03" or "2:03". */
export function clock(totalS: number): string {
  const s = Math.max(0, Math.floor(totalS));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

/** "ks_nordschleife@touristenfahrten" -> "Nordschleife · Touristenfahrten" */
export function prettyName(raw: string | undefined | null): string {
  if (!raw) return "";
  return raw
    .split("@")
    .map((part) =>
      part
        .replace(/^(ks|rss|acf|vrc|rt|lilski|ac)_/i, "")
        .split(/[_-]+/)
        .filter(Boolean)
        .map((w) => (w.length <= 3 && /\d/.test(w) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
        .join(" "),
    )
    .join(" · ");
}

export function gearLabel(g: number): string {
  return g < 0 ? "R" : g === 0 ? "N" : String(g);
}
