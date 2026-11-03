import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const rig = process.env.PITWALL_RIG ?? "http://localhost:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": rig,
      "/ws": { target: rig.replace(/^http/, "ws"), ws: true },
    },
  },
  test: { environment: "node" },
} as never);
