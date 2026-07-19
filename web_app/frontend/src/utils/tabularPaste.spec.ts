import { describe, expect, it } from 'vitest'
import { parseClipboardPreview } from './tabularPaste'

const aliases = ['生产日期', '班组', '炉号', '反应时间', '故障时间', '空烧时间', '产量', '源表小时产能']

describe('clipboard table preview', () => {
  it('recognizes an Excel tab-separated clipboard block and aliases', () => {
    const preview = parseClipboardPreview(`${aliases.join('\t')}\n2026-07-01\t白班张三\tE01\t8\t0\t0\t800\t100`)
    expect(preview.valid).toBe(true)
    expect(preview.delimiterLabel).toBe('制表符')
    expect(preview.totalRows).toBe(1)
    expect(preview.rows[0][2]).toBe('E01')
  })

  it('finds a semicolon header after metadata rows', () => {
    const preview = parseClipboardPreview(`生产系统导出\n2026-07-19\n${aliases.join(';')}\n2026-07-01;夜班李四;11A-01;6;1;0;540;90`)
    expect(preview.valid).toBe(true)
    expect(preview.delimiterLabel).toBe('分号')
    expect(preview.totalRows).toBe(1)
  })

  it('reports missing required columns before upload', () => {
    const preview = parseClipboardPreview('日期\t班组\t炉号\n2026-07-01\t白班张三\tE01')
    expect(preview.valid).toBe(false)
    expect(preview.missingHeaders).toContain('生产时间')
    expect(preview.error).toContain('缺少字段')
  })
})
