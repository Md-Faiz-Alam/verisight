import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Python package serves the built files, so visitors never need Node.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../src/verisight/web/static",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 700,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8010" },
  },
});
