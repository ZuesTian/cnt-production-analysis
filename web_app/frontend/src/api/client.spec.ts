import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, queryString } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('API client', () => {
  it('serializes filter arrays into stable shareable query parameters', () => {
    expect(queryString({ dataset_id: 'v1', production_lines: ['L3', '11A'], empty: [] })).toBe('?dataset_id=v1&production_lines=L3%2C11A')
  })

  it('recovers after a stable API error on a later retry', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 'NO_DATA', message: '暂无数据' }), { status: 404, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.datasets()).rejects.toMatchObject({ code: 'NO_DATA', message: '暂无数据' })
    await expect(api.datasets()).resolves.toEqual([])
  })
})
