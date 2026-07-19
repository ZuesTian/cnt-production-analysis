import path from 'node:path'
import { expect, test } from '@playwright/test'

const clipboardHeader = '日期\t班组\t炉号\t生产时间\t设备故障影响时间\t停机清理空烧\t产量\t小时产能'

function pastedRows(): string {
  const rows = [clipboardHeader]
  for (let day = 1; day <= 8; day += 1) {
    const date = `2026-07-${String(day).padStart(2, '0')}`
    rows.push(`${date}\t白班张三\tE01\t8\t0\t0\t800\t100`)
    rows.push(`${date}\t夜班李四\t11A-01\t6\t0\t0\t540\t90`)
  }
  return rows.join('\n')
}

test('opens and preflights an xlsx workbook as a temporary dataset', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  await page.goto('/data')
  await page.getByText('临时分析', { exact: true }).click()
  await page.locator('input[type=file]').setInputFiles(path.resolve(process.cwd(), '..', '..', 'tests', 'fixtures', 'import-sample.xlsx'))
  await expect(page.getByText('import-sample.xlsx', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '上传并预检' }).click()

  await expect(page.getByRole('heading', { name: '预检结果' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('16 条班次记录', { exact: false })).toBeVisible()
})

test('previews and imports an Excel clipboard block', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 980 })
  await page.goto('/data')
  await page.getByText('临时分析', { exact: true }).click()
  await page.getByText('粘贴表格', { exact: true }).click()
  await page.getByLabel('粘贴生产数据').fill(pastedRows())

  await expect(page.getByText(/已识别 制表符 · 8 列 · 约 16 行/)).toBeVisible()
  await expect(page.getByLabel('粘贴数据预览')).toContainText('E01')
  await page.getByRole('button', { name: '粘贴并预检' }).click()

  await expect(page.getByRole('heading', { name: '预检结果' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('16 条班次记录', { exact: false })).toBeVisible()
})
