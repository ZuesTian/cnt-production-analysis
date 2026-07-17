import { expect, test } from '@playwright/test'

test('interactive charts export both SVG and PNG locally', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  const firstChart = page.locator('.chart-frame').first()
  await expect(firstChart.locator('.chart-canvas svg')).toBeVisible()

  const svgDownload = page.waitForEvent('download')
  await firstChart.getByRole('button', { name: 'SVG' }).click()
  expect((await svgDownload).suggestedFilename()).toMatch(/\.svg$/)

  const pngDownload = page.waitForEvent('download')
  await firstChart.getByRole('button', { name: 'PNG' }).click()
  expect((await pngDownload).suggestedFilename()).toMatch(/\.png$/)
})
