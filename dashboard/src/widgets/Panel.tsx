/**
 * A block of the analysis you can minimise (click its header) and, when it
 * has a height, resize (drag the bar along its bottom; double-click resets).
 * Both are remembered on this device.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";

const KEY = "pitwall.panel.";

function load<T>(id: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(KEY + id);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

function save(id: string, v: unknown) {
  try {
    localStorage.setItem(KEY + id, JSON.stringify(v));
  } catch {
    /* private window etc.: just don't remember */
  }
}

export function Panel(props: {
  id: string;
  title: string;
  right?: ReactNode;
  children: ReactNode;
  /** Resizable height in px (the default); omit for content that sizes itself. */
  height?: number;
  minHeight?: number;
  className?: string;
}) {
  const { id, title, right, children, height, minHeight = 120, className = "" } = props;
  const [st, setSt] = useState(() => load(id, { open: true, h: height ?? 0 }));
  useEffect(() => save(id, st), [id, st]);
  const drag = useRef<{ y: number; h: number } | null>(null);

  const onDown = (e: React.PointerEvent) => {
    drag.current = { y: e.clientY, h: st.h || height || 300 };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const h = Math.max(minHeight, Math.min(1400, drag.current.h + e.clientY - drag.current.y));
    setSt((s) => ({ ...s, h }));
  };
  const onUp = () => {
    drag.current = null;
  };

  return (
    <section className={`pnl ${st.open ? "" : "pnl--closed"} ${className}`}>
      <header className="pnl__head">
        <button className="pnl__toggle" onClick={() => setSt((s) => ({ ...s, open: !s.open }))} aria-expanded={st.open}>
          <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden className="pnl__chev">
            <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="pnl__title">{title}</span>
        </button>
        {st.open && right && <span className="pnl__right">{right}</span>}
      </header>
      {st.open &&
        (height !== undefined ? (
          <>
            <div className="pnl__body pnl__body--sized" style={{ height: st.h || height }}>
              {children}
            </div>
            <div
              className="pnl__grip"
              role="separator"
              aria-label={`Resize ${title}`}
              title="Drag to resize · double-click to reset"
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onDoubleClick={() => setSt((s) => ({ ...s, h: height }))}
            />
          </>
        ) : (
          <div className="pnl__body">{children}</div>
        ))}
    </section>
  );
}

/** Drag bar between the analysis's two columns; returns the left column's share (%). */
export function useSplit(id: string, initial: number): [number, (e: React.PointerEvent<HTMLElement>) => void, () => void] {
  const [pct, setPct] = useState(() => load(id, { pct: initial }).pct);
  useEffect(() => save(id, { pct }), [id, pct]);
  const start = (e: React.PointerEvent<HTMLElement>) => {
    const el = e.currentTarget.parentElement;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const move = (ev: PointerEvent) => setPct(Math.max(28, Math.min(70, ((ev.clientX - box.left) / box.width) * 100)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return [pct, start, () => setPct(initial)];
}
