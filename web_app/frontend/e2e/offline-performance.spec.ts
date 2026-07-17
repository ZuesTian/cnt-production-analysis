import { expect, test } from '@playwright/test'

test('production workbench remains local-only and meets LAN interaction budgets', async ({ page }) => {
  const externalRequests: string[] = []
  const failedLocalRequests: string[] = []
  const badResponses: string[] = []
  const browserErrors: string[] = []

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    const isNetworkRequest = url.protocol === 'http:' || url.protocol === 'https:'
    const isLocal = ['127.0.0.1', 'localhost'].includes(url.hostname)
    if (isNetworkRequest && !isLocal) {
      externalRequests.push(url.href)
      await route.abort('internetdisconnected')
      return
    }
    await route.continue()
  })
  page.on('requestfailed', (request) => {
    const url = new URL(request.url())
    if (['127.0.0.1', 'localhost'].includes(url.hostname)) failedLocalRequests.push(request.url())
  })
  page.on('response', (response) => {
    if (response.status() >= 400) badResponses.push(`${response.status()} ${response.url()}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text())
  })
  page.on('pageerror', (error) => browserErrors.push(error.message))

  const firstPaintStart = Date.now()
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '生产总览', level: 1 })).toBeVisible()
  const firstInteractiveMs = Date.now() - firstPaintStart
  expect(firstInteractiveMs).toBeLessThan(2500)
  await expect(page.locator('.chart-canvas svg')).toHaveCount(2)

  const refreshResponse = page.waitForResponse((response) =>
    response.url().includes('/api/v1/dashboard/trends') && response.status() === 200,
  )
  const filterStart = Date.now()
  await page.locator('.field--grain .el-segmented__item').filter({ hasText: '班次' }).click()
  await refreshResponse
  await expect(page).toHaveURL(/grain=shift/)
  expect(Date.now() - filterStart).toBeLessThan(1000)

  expect(externalRequests).toEqual([])
  expect(failedLocalRequests).toEqual([])
  expect(badResponses).toEqual([])
  expect(browserErrors).toEqual([])
})
