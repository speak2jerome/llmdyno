import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

// The production build is served by the Python backend from llmdyno/web/static.
export default defineConfig({
  plugins: [react()],
  // the UI knows which release it was built from; scripts/bump_version.py keeps package.json in step with llmdyno/__init__.py
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: { outDir: "../llmdyno/web/static", emptyOutDir: true, chunkSizeWarningLimit: 1600 },
  server: {
    port: 5177,
    proxy: { "/api": "http://127.0.0.1:8777", "/ws": { target: "ws://127.0.0.1:8777", ws: true } },
  },
});
