import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useContextStore } from './context'

beforeEach(() => setActivePinia(createPinia()))

describe('filter context', () => {
  it('hydrates the explicit grain and global filters from a shared URL', () => {
    const store = useContextStore()
    store.hydrate({ dataset: 'abc', grain: 'shift', lines: 'L3,11A', furnaces: 'E01,E02', from: '2026-01-01', to: '2026-01-31' })
    expect(store.datasetId).toBe('abc')
    expect(store.grain).toBe('shift')
    expect(store.productionLines).toEqual(['L3', '11A'])
    expect(store.dateRange).toEqual(['2026-01-01', '2026-01-31'])
  })

  it('resets scope while preserving the selected dataset', () => {
    const store = useContextStore()
    store.datasetId = 'abc'; store.grain = 'shift'; store.productionLines = ['L3']
    store.resetScope()
    expect(store.datasetId).toBe('abc')
    expect(store.grain).toBe('furnace_day')
    expect(store.productionLines).toEqual([])
  })
})
