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

  it('logs in without forwarding a stale bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        access_token: 'signed-session',
        token_type: 'bearer',
        expires_in: 3600,
        user: { username: 'member', display_name: '成员' },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('stale-token')

    const session = await api.login('member', 'password')

    expect(session.user.display_name).toBe('成员')
    const options = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(options.headers)
    expect(headers.has('Authorization')).toBe(false)
    expect(JSON.parse(String(options.body))).toEqual({ username: 'member', password: 'password' })
  })

  it('posts pasted tabular data as a protected JSON import', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: 'job-1', dataset_id: 'data-1' }), { status: 202, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('signed-session')

    await api.importPastedDataset({ kind: 'temporary', name: '现场粘贴', content: '日期\t班组' })

    expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/datasets/paste-imports')
    const options = fetchMock.mock.calls[0][1] as RequestInit
    expect(options.method).toBe('POST')
    expect(JSON.parse(String(options.body))).toEqual({ kind: 'temporary', name: '现场粘贴', content: '日期\t班组' })
    expect(new Headers(options.headers).get('Authorization')).toBe('Bearer signed-session')
  })
})
