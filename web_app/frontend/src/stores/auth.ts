import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { AuthUser } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const loginRequired = ref(api.requiresLogin)
  const ready = ref(!loginRequired.value)
  const checking = ref(loginRequired.value)

  function clearSession() {
    api.clearAccessToken()
    user.value = null
    ready.value = !loginRequired.value
  }

  function requireAuthentication() {
    loginRequired.value = true
    clearSession()
  }

  async function initialize() {
    if (!loginRequired.value && !api.hasAccessToken()) {
      checking.value = false
      ready.value = true
      return
    }
    if (!api.hasAccessToken()) {
      checking.value = false
      ready.value = false
      return
    }
    checking.value = true
    try {
      user.value = await api.me()
      ready.value = true
    } catch {
      clearSession()
    } finally {
      checking.value = false
    }
  }

  async function login(username: string, password: string) {
    checking.value = true
    try {
      const session = await api.login(username.trim(), password)
      api.setAccessToken(session.access_token)
      user.value = session.user
      ready.value = true
    } finally {
      checking.value = false
    }
  }

  async function logout() {
    try {
      if (api.hasAccessToken()) await api.logout()
    } catch {
      // A failed or expired remote session must not prevent local logout.
    } finally {
      clearSession()
    }
  }

  return {
    user,
    loginRequired,
    ready,
    checking,
    initialize,
    login,
    logout,
    requireAuthentication,
  }
})
