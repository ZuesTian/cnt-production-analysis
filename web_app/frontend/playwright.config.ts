import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 150_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: {
      executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    },
  },
  webServer: {
    command: 'G:\\Anaconda\\python.exe -m uvicorn main:app --app-dir .. --host 127.0.0.1 --port 8765',
    url: 'http://127.0.0.1:8765/api/v1/health',
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
