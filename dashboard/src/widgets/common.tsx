import { useEffect, useRef, useState, type ReactNode } from "react";

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
export function useSize<T extends HTMLElement>(): [React.RefObject<T>, { w: number; h: number }] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((s) => (s.w === width && s.h === height ? s : { w: width, h: height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
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
