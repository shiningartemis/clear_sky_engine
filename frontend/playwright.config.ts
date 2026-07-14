import { defineConfig, devices } from "@playwright/test";

function readPort(name: string, fallback: number): number {
  const value = process.env[name];
  const port = value === undefined ? fallback : Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} 必须是有效端口`);
  }
  return port;
}

const backendPort = readPort("CLEAR_SKY_E2E_BACKEND_PORT", 18_000);
const frontendPort = readPort("CLEAR_SKY_E2E_FRONTEND_PORT", 15_173);
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  outputDir: "../test-results",
  reporter: [
    ["line"],
    ["html", { open: "never", outputFolder: "../playwright-report" }],
  ],
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command:
        `powershell -ExecutionPolicy Bypass -File ../scripts/prepare-e2e-content.ps1 ` +
        `-StartBackend -Port ${backendPort}`,
      url: `${backendUrl}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: frontendUrl,
      env: { CLEAR_SKY_BACKEND_URL: backendUrl },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
