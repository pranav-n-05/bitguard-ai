import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests run against a live stack:
 *   - backend on :8000 (or BITGUARD_E2E_URL pointing at nginx, e.g. http://localhost:8080)
 *   - this config starts the Vite dev server (proxying /api) unless BITGUARD_E2E_URL is set.
 * Credentials: BITGUARD_E2E_EMAIL / BITGUARD_E2E_PASSWORD (an administrator).
 */
const external = process.env.BITGUARD_E2E_URL
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: external ?? 'http://localhost:5173', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: external ? undefined : { command: 'npm run dev -- --strictPort', url: 'http://localhost:5173', reuseExistingServer: true, timeout: 60_000 },
})
