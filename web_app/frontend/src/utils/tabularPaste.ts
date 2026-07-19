export const REQUIRED_SOURCE_HEADERS = [
  '日期',
  '班组',
  '炉号',
  '生产时间',
  '设备故障影响时间',
  '停机清理空烧',
  '产量',
  '小时产能',
] as const

const aliases: Record<string, string[]> = {
  日期: ['日期', '生产日期', 'date', 'productiondate'],
  班组: ['班组', '班次班组', '班次/班组', 'team', 'shiftteam'],
  炉号: ['炉号', '炉次', '设备炉号', 'furnace', 'furnaceid'],
  生产时间: ['生产时间', '反应时间', '生产时长', 'reactiontime'],
  设备故障影响时间: ['设备故障影响时间', '故障时间', '故障时长', 'faulttime'],
  停机清理空烧: ['停机清理空烧', '停机清理/空烧', '清理空烧时间', '空烧时间', 'cleanemptyburntime'],
  产量: ['产量', '生产量', 'output', 'productionoutput'],
  小时产能: ['小时产能', '源表小时产能', '小时产量', 'yield', 'hourlyoutput'],
}

function normalizeHeader(value: string): string {
  return value
    .replace(/^\uFEFF/, '')
    .trim()
    .toLocaleLowerCase()
    .replace(/[\s\u3000]+/g, '')
    .replace(/[（(](?:h|小时|kg\/h|公斤\/小时)[）)]$/i, '')
}

const aliasLookup = new Map<string, string>()
Object.entries(aliases).forEach(([canonical, values]) => {
  values.forEach((value) => aliasLookup.set(normalizeHeader(value), canonical))
})

function parseRows(value: string, delimiter: string, limit = 40): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let index = 0; index < value.length && rows.length < limit; index += 1) {
    const character = value[index]
    if (character === '"') {
      if (quoted && value[index + 1] === '"') {
        field += '"'
        index += 1
      } else quoted = !quoted
    } else if (character === delimiter && !quoted) {
      row.push(field.trim())
      field = ''
    } else if ((character === '\n' || character === '\r') && !quoted) {
      if (character === '\r' && value[index + 1] === '\n') index += 1
      row.push(field.trim())
      if (row.some((cell) => cell.length > 0)) rows.push(row)
      row = []
      field = ''
    } else field += character
  }
  if (rows.length < limit && (field.length > 0 || row.length > 0)) {
    row.push(field.trim())
    if (row.some((cell) => cell.length > 0)) rows.push(row)
  }
  return rows
}

function headerMatches(row: string[]): Set<string> {
  return new Set(row.map((value) => aliasLookup.get(normalizeHeader(value))).filter((value): value is string => Boolean(value)))
}

function detectDelimiter(value: string): { delimiter: string; rows: string[][] } | null {
  let best: { delimiter: string; rows: string[][]; exact: number; width: number; priority: number } | null = null
  const delimiters = ['\t', ',', ';', '|']
  for (const [priority, delimiter] of delimiters.entries()) {
    const rows = parseRows(value, delimiter)
    const width = Math.max(0, ...rows.map((row) => row.length))
    const exact = rows.some((row) => REQUIRED_SOURCE_HEADERS.every((header) => headerMatches(row).has(header))) ? 1 : 0
    const candidate = { delimiter, rows, exact, width, priority }
    if (!best || exact > best.exact || (exact === best.exact && width > best.width) || (exact === best.exact && width === best.width && priority < best.priority)) best = candidate
  }
  return best && best.width > 1 ? { delimiter: best.delimiter, rows: best.rows } : null
}

export interface PastePreview {
  delimiter: string
  delimiterLabel: string
  headers: string[]
  rows: string[][]
  totalRows: number
  columnCount: number
  missingHeaders: string[]
  valid: boolean
  error: string
}

export function parseClipboardPreview(value: string): PastePreview {
  const empty: PastePreview = {
    delimiter: '', delimiterLabel: '', headers: [], rows: [], totalRows: 0,
    columnCount: 0, missingHeaders: [...REQUIRED_SOURCE_HEADERS], valid: false, error: '',
  }
  if (!value.trim()) return empty
  const detected = detectDelimiter(value)
  if (!detected) return { ...empty, error: '未识别到表格分隔符，请从 Excel 复制单元格区域，或粘贴 CSV/TSV 文本。' }
  const headerIndex = detected.rows.findIndex((row) => {
    const matches = headerMatches(row)
    return REQUIRED_SOURCE_HEADERS.every((header) => matches.has(header))
  })
  const effectiveHeader = headerIndex >= 0 ? headerIndex : 0
  const headers = detected.rows[effectiveHeader] || []
  const matches = headerMatches(headers)
  const missingHeaders = REQUIRED_SOURCE_HEADERS.filter((header) => !matches.has(header))
  const dataRows = detected.rows.slice(effectiveHeader + 1).filter((row) => row.some(Boolean))
  const physicalRows = value.split(/\r?\n/).filter((line) => line.trim()).length
  const delimiterLabel = ({ '\t': '制表符', ',': '逗号', ';': '分号', '|': '竖线' } as Record<string, string>)[detected.delimiter]
  return {
    delimiter: detected.delimiter,
    delimiterLabel,
    headers,
    rows: dataRows.slice(0, 8),
    totalRows: Math.max(0, physicalRows - effectiveHeader - 1),
    columnCount: headers.length,
    missingHeaders,
    valid: missingHeaders.length === 0 && dataRows.length > 0,
    error: missingHeaders.length ? `缺少字段：${missingHeaders.join('、')}` : dataRows.length ? '' : '表头后没有数据行。',
  }
}
