/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API to the FastAPI service (`make run`, port 8080).
const api = { target: "http://localhost:8080", changeOrigin: false };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/sandbox": api, "/assist": api, "/healthz": api } },
  test: { environment: "node" },
});
