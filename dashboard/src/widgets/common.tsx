import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export function Card({
  title,
  right,
  children,
  className = "",
  dim = false,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  dim?: boolean;
}) {
  return (
    <section className={`card ${dim ? "card--dim" : ""} ${className}`}>
      {(title || right) && (
        <header className="card__head">
          {title && <span className="card__title">{title}</span>}
          {right && <span className="card__right">{right}</span>}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}

/** Tracks an element's size (for SVG layouts that need pixel dimensions). */
/**
 * Measures an element's size. Uses a callback ref so it keeps working when the
 * element appears later (a chart waiting for data, a view waiting for the track).
 */
export function useSize<T extends HTMLElement>(): [(el: T | null) => void, { w: number; h: number }] {
  const [size, setSize] = useState({ w: 0, h: 0 });
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, size];
}

/** Placeholder for widgets that arrive in a later phase. */
export function Upcoming({ title, phase, note }: { title: string; phase: number; note: string }) {
  return (
    <Card title={title} right={<span className="pill">phase {phase}</span>} dim>
      <div className="upcoming">{note}</div>
    </Card>
  );
}
