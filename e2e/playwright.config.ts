import os from "node:os";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// One workspace path for the run; each test wipes it and starts a fresh Core (see fixtures.ts).
process.env.PBS_E2E_WORKSPACE ??= path.join(os.tmpdir(), `pbs-e2e-${process.pid}`);
const CORE_PORT = Number(process.env.PBS_E2E_CORE_PORT ?? 18765);
const UI_PORT = Number(process.env.PBS_E2E_UI_PORT ?? 15173);
process.env.PBS_E2E_CORE_PORT = String(CORE_PORT);
process.env.PBS_E2E_UI_PORT = String(UI_PORT);

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  workers: 1, // tests share the UI server and restart Core; run them serially
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    trace: "retain-on-failure",
    acceptDownloads: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm --filter studio-ui exec vite --port ${UI_PORT} --strictPort`,
    cwd: path.resolve(__dirname, ".."),
    url: `http://127.0.0.1:${UI_PORT}`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      PBS_WORKSPACE: process.env.PBS_E2E_WORKSPACE,
      PBS_CORE_URL: `http://127.0.0.1:${CORE_PORT}`,
      PBS_UI_PORT: String(UI_PORT),
    },
  },
});
