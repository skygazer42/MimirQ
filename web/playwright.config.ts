import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.PLAYWRIGHT_PORT || 3100)
const baseURL = `http://127.0.0.1:${PORT}`
const useProdServer = Boolean(process.env.CI) || process.env.PLAYWRIGHT_USE_PROD_SERVER === '1'
const LOCAL_NO_PROXY_HOSTS = ['127.0.0.1', 'localhost']

function ensureLocalNoProxy(envName: 'NO_PROXY' | 'no_proxy') {
  const current = process.env[envName] || ''
  const entries = new Set(
    current
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)
  )
  for (const host of LOCAL_NO_PROXY_HOSTS) entries.add(host)
  process.env[envName] = Array.from(entries).join(',')
}

// The local webServer readiness probe must never be routed through a global proxy.
ensureLocalNoProxy('NO_PROXY')
ensureLocalNoProxy('no_proxy')

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results/playwright',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  timeout: 120_000,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    navigationTimeout: 90_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    viewport: { width: 1600, height: 1000 },
  },
  webServer: {
    command: useProdServer
      ? `pnpm exec next build --webpack && pnpm exec next start -H 127.0.0.1 -p ${PORT}`
      : `pnpm exec next dev --webpack -H 127.0.0.1 -p ${PORT}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI && !useProdServer,
    stdout: 'pipe',
    stderr: 'pipe',
    timeout: useProdServer ? 900_000 : 120_000,
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
