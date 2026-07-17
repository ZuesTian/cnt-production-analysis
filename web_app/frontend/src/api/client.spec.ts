import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, clearAccessToken, queryString, setAccessToken } from './client'

afterEach(() => {
  clearAccessToken()
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

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

  it('sends the runtime access token and stable workspace header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('test-secret')

    await api.datasets()

    const options = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(options.headers)
    expect(headers.get('Authorization')).toBe('Bearer test-secret')
    expect(headers.get('X-CNT-Workspace')).toMatch(/^[a-z0-9]{32}$/)
  })
})
