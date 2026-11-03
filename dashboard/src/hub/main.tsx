import "@fontsource-variable/inter";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import { HubApp } from "./HubApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HubApp />
  </StrictMode>,
);
