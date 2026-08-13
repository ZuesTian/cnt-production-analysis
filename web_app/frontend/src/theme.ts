import { ref } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'cnt-lab-theme'
const mediaQuery = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(prefers-color-scheme: dark)')
  : null

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

export const activeTheme = ref<Theme>(storedTheme() || (mediaQuery?.matches ? 'dark' : 'light'))

export function applyTheme(theme: Theme, persist = false) {
  activeTheme.value = theme
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#081a18' : '#f3f5f0')
  }
  if (persist) {
    try { localStorage.setItem(STORAGE_KEY, theme) } catch { /* storage can be unavailable */ }
  }
}

let initialized = false

export function initializeTheme() {
  applyTheme(activeTheme.value)
  if (initialized) return
  initialized = true
  mediaQuery?.addEventListener?.('change', (event) => {
    if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light')
  })
}

export function toggleTheme() {
  applyTheme(activeTheme.value === 'dark' ? 'light' : 'dark', true)
}
