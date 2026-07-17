import { expect, test } from '@playwright/test'

const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 1024, height: 768 },
  { name: 'mobile', width: 390, height: 844 },
]

for (const viewport of viewports) {
  test(`${viewport.name} production overview has no horizontal overflow`, async ({ page }, testInfo) => {
    const browserMessages: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') browserMessages.push(message.text())
    })
    page.on('pageerror', (error) => browserMessages.push(error.message))
    await page.setViewportSize(viewport)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '生产总览', level: 1 })).toBeVisible()
    await expect(page.locator('.chart-canvas svg')).toHaveCount(2, { timeout: 30_000 })
    const geometry = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }))
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1)
    const targetSelector = viewport.name === 'mobile'
      ? '.mobile-nav a:visible, .mobile-filter-button:visible, .chart-actions button:visible'
      : '.primary-nav a:visible, .collapse-button:visible, .filter-row button:visible, .field .el-select__wrapper:visible, .field .el-input__wrapper:visible, .field .el-segmented:visible, .chart-actions button:visible'
    const allCoreTargets = await page.locator(targetSelector).evaluateAll((nodes) =>
      nodes.map((node) => {
        const rect = node.getBoundingClientRect()
        return { width: rect.width, height: rect.height }
      }),
    )
    expect(allCoreTargets.length).toBeGreaterThan(0)
    expect(allCoreTargets.every((item) => item.width >= 44 && item.height >= 44)).toBeTruthy()
    if (viewport.name === 'mobile') {
      await expect(page.locator('.mobile-nav')).toBeVisible()
      await expect(page.locator('.sidebar')).toBeHidden()
    }
    expect(browserMessages).toEqual([])
    const screenshotPath = testInfo.outputPath(`dashboard-${viewport.name}.png`)
    await page.screenshot({ path: screenshotPath, fullPage: false })
    await testInfo.attach(`dashboard-${viewport.name}`, { path: screenshotPath, contentType: 'image/png' })
  })
}
