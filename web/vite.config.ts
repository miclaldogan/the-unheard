import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

// Local HTTPS for phone testing: run scripts/mkcert.sh (creates web/certs/dev.pem + dev-key.pem).
// When the files exist the dev server serves https:// and proxies /api to the Python backend.
const certDir = path.resolve(__dirname, "certs");
const certFile = path.join(certDir, "dev.pem");
const keyFile = path.join(certDir, "dev-key.pem");
const https =
  fs.existsSync(certFile) && fs.existsSync(keyFile)
    ? { cert: fs.readFileSync(certFile), key: fs.readFileSync(keyFile) }
    : undefined;

const backend = process.env.UNHEARD_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.UNHEARD_LAN ? "0.0.0.0" : "127.0.0.1",
    port: 5173,
    https,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
