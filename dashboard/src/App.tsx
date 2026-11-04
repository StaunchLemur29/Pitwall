import { useEffect, useState } from "react";
import { useRig } from "./lib/rig";
import { Dashboard } from "./views/Dashboard";
import { AnalysisPage } from "./views/AnalysisPage";
import { Settings } from "./views/Settings";
import { useFullscreenKey } from "./widgets/Fullscreen";
import { Tools } from "./views/Tools";
import { WhatsNew } from "./views/WhatsNew";
import { Toasts } from "./widgets/Toasts";

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
  useFullscreenKey();
  const accent = useRig((s) => s.config?.display.accent);
  useEffect(() => {
    if (accent) document.documentElement.style.setProperty("--accent", accent);
  }, [accent]);
  const page = route.startsWith("/news") ? <WhatsNew /> : route.startsWith("/tools") ? <Tools /> : route.startsWith("/settings") ? <Settings /> : route.startsWith("/analysis") ? <AnalysisPage /> : <Dashboard />;
  return (
    <>
      {page}
      <Toasts />
    </>
  );
}
