import { describe, expect, it } from 'vitest'
import { deltaTone, formatMetric } from './metrics'

describe('KPI presentation', () => {
  it('formats missing and weighted values without inventing precision', () => {
    expect(formatMetric(null, 'kg/h')).toBe('—')
    expect(formatMetric(1234.56, 'kg')).toContain('1,235')
    expect(formatMetric(81.26, 'kg/h')).toContain('81.3')
  })

  it('treats rising fault time as risk and rising output as good', () => {
    expect(deltaTone('fault_hours', 12)).toBe('risk')
    expect(deltaTone('total_output', 12)).toBe('good')
  })
})
