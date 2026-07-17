import { expect, test } from '@playwright/test'

function makeCsv(unique: number): Buffer {
  const header = '日期,班组,炉号,生产时间,设备故障影响时间,停机清理空烧,产量,小时产能'
  const rows: string[] = [header]
  for (let index = 0; index < 8; index += 1) {
    const day = String(index + 1).padStart(2, '0')
    rows.push(`2026-06-${day},白班张三${unique},E01,8,0,0,${800 + (unique % 7)},100`)
    rows.push(`2026-06-${day},夜班李四,E02,8,0,0,760,95`)
    rows.push(`2026-06-${day},白班王五,11A-01,8,0,0,720,90`)
    rows.push(`2026-06-${day},夜班赵六,11A-02,8,0,0,680,85`)
  }
  return Buffer.from(`\uFEFF${rows.join('\n')}`, 'utf-8')
}

test('import, preview, publish, analyze, export and rollback', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const beforeResponse = await page.request.get('/api/v1/datasets')
  const before = await beforeResponse.json() as Array<{ id: string; name: string; status: string }>
  const previous = before.find((item) => item.status === 'published')
  expect(previous).toBeTruthy()

  const unique = Date.now()
  await page.goto('/data')
  await expect(page.getByRole('heading', { name: '数据管理', level: 1 })).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({
    name: `e2e-${unique}.csv`,
    mimeType: 'text/csv',
    buffer: makeCsv(unique),
  })
  await page.getByLabel('版本名称').fill(`E2E 验收 ${unique}`)
  await page.getByRole('button', { name: '上传并预检' }).click()
  await expect(page.getByRole('heading', { name: '预检结果' })).toBeVisible({ timeout: 60_000 })
  await page.locator('.quality-preview .el-checkbox').click()
  await page.getByRole('button', { name: '二次确认并发布' }).click()
  await page.getByRole('button', { name: '确认发布' }).click()
  await expect(page.getByText('共享数据已发布')).toBeVisible()

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '生产总览', level: 1 })).toBeVisible()
  await expect(page.getByText('E2E 验收', { exact: false }).first()).toBeVisible()

  await page.goto('/reports')
  const dailyCard = page.locator('.report-card').filter({ hasText: '每日生产汇总' })
  await dailyCard.getByRole('button', { name: '生成报表' }).click()
  await expect(page.getByText('报表已生成')).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('.exports-panel').getByRole('link', { name: '下载' }).first()).toBeVisible()

  await page.goto('/data')
  const previousRow = page.getByRole('row').filter({ hasText: previous!.name }).first()
  await previousRow.getByRole('button', { name: '回滚至此' }).click()
  await page.getByRole('button', { name: '确认回滚' }).click()
  await expect(page.getByText('活动数据版本已回滚')).toBeVisible()
})
