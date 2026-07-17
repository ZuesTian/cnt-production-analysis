export function formatMetric(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const maximumFractionDigits = unit === 'kg' ? 0 : 1
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(value)}${unit ? ` ${unit}` : ''}`
}

export function deltaTone(key: string, delta: number | null): 'neutral' | 'good' | 'risk' {
  if (delta === null || delta === 0) return 'neutral'
  if (key === 'fault_hours') return delta > 0 ? 'risk' : 'good'
  return delta > 0 ? 'good' : 'risk'
}
