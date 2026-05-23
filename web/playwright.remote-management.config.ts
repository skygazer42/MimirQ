import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_LIVE_BASE_URL || 'http://127.0.0.1:3000'

export default defineConfig({
  testDir: './e2e',
  testMatch: /management-surfaces\.live\.spec\.ts/,
  outputDir: './test-results/playwright-remote-management',
  fullyParallel: false,
  forbidOnly: false,
  retries: 0,
  timeout: 240_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL,
    navigationTimeout: 120_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    viewport: { width: 1600, height: 1000 },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],
})
