/** Fullscreen on any page: a header button, and "F" when you're not typing. */
import { useEffect, useState } from "react";

const supported = () => typeof document !== "undefined" && !!document.fullscreenEnabled;

export function toggleFullscreen(): void {
  if (!supported()) return;
  if (document.fullscreenElement) void document.exitFullscreen();
  else void document.documentElement.requestFullscreen().catch(() => {});
}

function typing(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

/** "F" toggles fullscreen (not while typing in a box, not with Ctrl/Alt/Cmd). */
export function useFullscreenKey(): void {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.altKey && !e.metaKey && !typing(e.target)) toggleFullscreen();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);
}

/** Header button; hidden where the browser can't go fullscreen (e.g. iPhone Safari). */
export function FullscreenButton({ className = "dash__close" }: { className?: string }) {
  const [on, setOn] = useState(() => supported() && !!document.fullscreenElement);
  useEffect(() => {
    const ch = () => setOn(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", ch);
    return () => document.removeEventListener("fullscreenchange", ch);
  }, []);
  if (!supported()) return null;
  const label = on ? "Exit fullscreen (F)" : "Fullscreen (F)";
  return (
    <button className={`${className} fsbtn`} onClick={toggleFullscreen} title={label} aria-label={label}>
      <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        {on ? (
          <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
        ) : (
          <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
        )}
      </svg>
    </button>
  );
}
