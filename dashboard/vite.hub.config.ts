// The hub (laps from the cloud): a separate build of the same code, deployed to Vercel.
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, open: "/hub.html" },
  build: {
    outDir: "dist-hub",
    rollupOptions: { input: { index: resolve(__dirname, "hub.html") } },
  },
});
