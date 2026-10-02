import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const DATA = process.env.E2E_DATA_DIR ?? "/tmp/cardiolens-e2e";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    launchOptions: {
      executablePath: process.env.PW_CHROMIUM ?? undefined,
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
    },
    permissions: ["microphone"],
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: {
    // Serves the built SPA + API from one process with a fresh, demo-seeded database.
    command: `rm -rf ${DATA} && mkdir -p ${DATA} && cd ../backend && CARDIOLENS_DATABASE_URL=sqlite:///${DATA}/e2e.db CARDIOLENS_STORAGE_DIR=${DATA}/rec python3 -m uvicorn app.main:app --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
