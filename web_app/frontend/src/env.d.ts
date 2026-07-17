/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_BASE_PATH?: string
  readonly VITE_REQUIRE_API_KEY?: string
  readonly VITE_ROUTER_MODE?: 'hash' | 'history'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
