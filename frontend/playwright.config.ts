import { defineConfig } from '@playwright/test'
import path from 'node:path'

// One command runs everything: it builds nothing (run `npm run build` first), starts a throw-away
// seeded copy of the app on :8002 (scripts/e2e_server.py) and drives it in a real browser.
const root = path.resolve(import.meta.dirname, '..')
const python = process.platform === 'win32' ? path.join(root, '.venv', 'Scripts', 'python.exe') : path.join(root, '.venv', 'bin', 'python')

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:8002',
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `"${python}" "${path.join(root, 'scripts', 'e2e_server.py')}"`,
    url: 'http://localhost:8002/api/health',
    timeout: 240_000,
    cwd: root,
    reuseExistingServer: false,
    stdout: 'pipe',
  },
})
