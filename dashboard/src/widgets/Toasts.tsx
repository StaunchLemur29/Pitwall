/** Short pop-up confirmations ("Drill set: …") in the corner of the window. */
import { useSyncExternalStore } from "react";

export type ToastTone = "ok" | "warn" | "bad";
interface Toast {
  id: number;
  text: string;
  tone: ToastTone;
}

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Show a message for a few seconds. */
export function toast(text: string, tone: ToastTone = "ok", ms = 4000): void {
  const t = { id: nextId++, text, tone };
  toasts = [...toasts.slice(-2), t]; // at most three at once
  emit();
  setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== t.id);
    emit();
  }, ms);
}

export function Toasts() {
  const list = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => toasts,
  );
  if (!list.length) return null;
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
