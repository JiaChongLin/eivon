import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  use: {
    baseURL: "http://127.0.0.1:18787",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.EIVON_TEST_CHROME ? { executablePath: process.env.EIVON_TEST_CHROME } : {},
  },
  webServer: {
    command: "cd .. && .venv/bin/python scripts/serve_e2e.py",
    url: "http://127.0.0.1:18787/health/ready",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
