import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    // Dev only: proxy API calls to the FastAPI backend. In production the same
    // origin serves both, so relative /api paths just work.
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
