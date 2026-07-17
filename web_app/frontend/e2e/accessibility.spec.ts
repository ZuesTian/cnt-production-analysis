import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const targets = [
  { path: '/', width: 1440, height: 900 },
  { path: '/data', width: 1440, height: 900 },
  { path: '/', width: 390, height: 844 },
]

for (const target of targets) {
  test(`WCAG serious and critical audit ${target.path} at ${target.width}px`, async ({ page }) => {
    await page.setViewportSize({ width: target.width, height: target.height })
    await page.goto(target.path)
    await page.locator('h1').waitFor()
    await page.waitForLoadState('networkidle')
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const severe = result.violations.filter((violation) => ['critical', 'serious'].includes(violation.impact || ''))
    expect(severe, severe.map((violation) => `${violation.id}: ${violation.help}`).join('\n')).toEqual([])
  })
}
