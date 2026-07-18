import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => ({
  requiresLogin: true,
  hasAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  clearAccessToken: vi.fn(),
  login: vi.fn(),
  me: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('@/api/client', () => ({ api: apiMock }))

import { useAuthStore } from './auth'

describe('authentication store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.hasAccessToken.mockReturnValue(false)
    apiMock.requiresLogin = true
  })

  it('requires login when no browser session exists', async () => {
    const auth = useAuthStore()
    await auth.initialize()
    expect(auth.ready).toBe(false)
    expect(auth.checking).toBe(false)
    expect(auth.user).toBeNull()
  })

  it('switches an optional local build to login after an API 401', () => {
    apiMock.requiresLogin = false
    const auth = useAuthStore()
    expect(auth.ready).toBe(true)

    auth.requireAuthentication()

    expect(auth.loginRequired).toBe(true)
    expect(auth.ready).toBe(false)
    expect(apiMock.clearAccessToken).toHaveBeenCalled()
  })

  it('stores a signed session and clears it on logout', async () => {
    apiMock.login.mockResolvedValue({
      access_token: 'signed-session',
      token_type: 'bearer',
      expires_in: 3600,
      user: { username: 'member', display_name: '成员' },
    })
    apiMock.hasAccessToken.mockReturnValue(true)
    apiMock.logout.mockResolvedValue({ status: 'ok' })
    const auth = useAuthStore()

    await auth.login('member', 'password')
    expect(apiMock.setAccessToken).toHaveBeenCalledWith('signed-session')
    expect(auth.user).toEqual({ username: 'member', display_name: '成员' })
    expect(auth.ready).toBe(true)

    await auth.logout()
    expect(apiMock.logout).toHaveBeenCalledOnce()
    expect(apiMock.clearAccessToken).toHaveBeenCalled()
    expect(auth.user).toBeNull()
    expect(auth.ready).toBe(false)
  })
})
