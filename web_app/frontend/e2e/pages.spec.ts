import { expect, test } from '@playwright/test'

const pages = [
  { path: '/furnaces', heading: '炉号分析', chartCount: 2 },
  { path: '/diagnostics', heading: '异常与故障', chartCount: 1 },
  { path: '/reports', heading: '报表中心', chartCount: 0 },
  { path: '/data', heading: '数据管理', chartCount: 0 },
]

for (const target of pages) {
  test(`${target.heading} renders production data without console errors`, async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
    page.on('pageerror', (error) => errors.push(error.message))
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(target.path)
    await expect(page.getByRole('heading', { name: target.heading, level: 1 })).toBeVisible()
    if (target.chartCount) await expect(page.locator('.chart-canvas svg')).toHaveCount(target.chartCount, { timeout: 30_000 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
    expect(errors).toEqual([])
    const screenshotPath = testInfo.outputPath(`${target.heading}.png`)
    await page.screenshot({ path: screenshotPath, fullPage: false })
    await testInfo.attach(target.heading, { path: screenshotPath, contentType: 'image/png' })
  })
}
