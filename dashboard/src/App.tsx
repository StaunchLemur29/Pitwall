import { useEffect, useState } from "react";
import { useRig } from "./lib/rig";
import { Dashboard } from "./views/Dashboard";
import { AnalysisPage } from "./views/AnalysisPage";
import { Settings } from "./views/Settings";

function useHashRoute(): string {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#/, "") || "/";
}

export function App() {
  const route = useHashRoute();
  const accent = useRig((s) => s.config?.display.accent);
  useEffect(() => {
    if (accent) document.documentElement.style.setProperty("--accent", accent);
  }, [accent]);
  if (route.startsWith("/settings")) return <Settings />;
  if (route.startsWith("/analysis")) return <AnalysisPage />;
  return <Dashboard />;
}
