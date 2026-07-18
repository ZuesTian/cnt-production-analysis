import type {
  ApiErrorBody,
  AuthUser,
  DatasetSummary,
  ExportArtifact,
  FilterOptions,
  JobStatus,
  LoginResponse,
  OverviewResponse,
  QualityReport,
  SeriesResponse,
} from '@/types/api'

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: unknown,
  ) {
    super(message)
  }
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const ACCESS_TOKEN_KEY = 'cnt_production_api_token'
const WORKSPACE_KEY = 'cnt_production_workspace'

function storageAvailable(): boolean {
  return typeof window !== 'undefined' && Boolean(window.localStorage)
}

function workspaceId(): string {
  if (!storageAvailable()) return 'server-rendered-workspace-id'
  const existing = window.localStorage.getItem(WORKSPACE_KEY)
  if (existing && /^[A-Za-z0-9_-]{24,64}$/.test(existing)) return existing
  const created = crypto.randomUUID().replaceAll('-', '')
  window.localStorage.setItem(WORKSPACE_KEY, created)
  return created
}

export function apiEndpoint(path: string): string {
  return `${API_BASE_URL}${path}`
}

export function getAccessToken(): string {
  return storageAvailable() ? window.localStorage.getItem(ACCESS_TOKEN_KEY) || '' : ''
}

export function setAccessToken(token: string): void {
  if (storageAvailable()) window.localStorage.setItem(ACCESS_TOKEN_KEY, token.trim())
}

export function clearAccessToken(): void {
  if (storageAvailable()) window.localStorage.removeItem(ACCESS_TOKEN_KEY)
}

function requestHeaders(options?: RequestInit): Headers {
  const headers = new Headers(options?.headers)
  if (!(options?.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  headers.set('X-CNT-Workspace', workspaceId())
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

async function fetchResponse(url: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(apiEndpoint(url), {
    ...options,
    credentials: API_BASE_URL ? 'omit' : 'same-origin',
    headers: requestHeaders(options),
  })
  if (response.status === 401 && url !== '/api/v1/auth/login' && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('cnt-auth-required'))
  }
  return response
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetchResponse(url, options)
  if (!response.ok) {
    let body: ApiErrorBody = { code: 'NETWORK_ERROR', message: `请求失败（${response.status}）` }
    try { body = await response.json() as ApiErrorBody } catch { /* keep stable fallback */ }
    throw new ApiError(body.code, body.message, response.status, body.details)
  }
  return response.json() as Promise<T>
}

export function queryString(values: Record<string, string | string[] | undefined | null>): string {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (Array.isArray(value) && value.length) params.set(key, value.join(','))
    else if (typeof value === 'string' && value) params.set(key, value)
  })
  const result = params.toString()
  return result ? `?${result}` : ''
}

export const api = {
  requiresLogin: import.meta.env.VITE_REQUIRE_LOGIN === 'true',
  requiresAccessKey: import.meta.env.VITE_REQUIRE_API_KEY === 'true',
  hasAccessToken: () => Boolean(getAccessToken()),
  setAccessToken,
  clearAccessToken,
  verifyAccess: () => request<{ status: string }>('/api/v1/auth/check'),
  login: (username: string, password: string) => {
    clearAccessToken()
    return request<LoginResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
  },
  me: () => request<AuthUser>('/api/v1/auth/me'),
  logout: () => request<{ status: string }>('/api/v1/auth/logout', { method: 'POST' }),
  datasets: () => request<DatasetSummary[]>('/api/v1/datasets'),
  quality: (id: string) => request<QualityReport>(`/api/v1/datasets/${id}/quality`),
  filters: (id?: string) => request<FilterOptions>(`/api/v1/filters${queryString({ dataset_id: id })}`),
  overview: (query: Record<string, string | string[] | undefined>) => request<OverviewResponse>(`/api/v1/dashboard/overview${queryString(query)}`),
  trends: (query: Record<string, string | string[] | undefined>) => request<SeriesResponse>(`/api/v1/dashboard/trends${queryString(query)}`),
  ranking: (query: Record<string, string | string[] | undefined>) => request<SeriesResponse>(`/api/v1/furnaces/ranking${queryString(query)}`),
  furnace: (id: string, query: Record<string, string | string[] | undefined>) => request<SeriesResponse>(`/api/v1/furnaces/${encodeURIComponent(id)}${queryString(query)}`),
  diagnostics: (kind: string, query: Record<string, string | string[] | undefined>) => request<SeriesResponse>(`/api/v1/diagnostics/${kind}${queryString(query)}`),
  jobs: () => request<JobStatus[]>('/api/v1/jobs'),
  job: (id: string) => request<JobStatus>(`/api/v1/jobs/${id}`),
  exports: () => request<ExportArtifact[]>('/api/v1/exports'),
  createExport: (body: Record<string, unknown>) => request<{ job_id: string; dataset_id: string }>('/api/v1/exports', { method: 'POST', body: JSON.stringify(body) }),
  publish: (id: string, body: Record<string, unknown>, activate = false) => request<DatasetSummary>(`/api/v1/datasets/${id}/${activate ? 'activate' : 'publish'}`, { method: 'POST', body: JSON.stringify(body) }),
  importDataset: (form: FormData) => request<{ job_id: string; dataset_id: string }>('/api/v1/datasets/imports', { method: 'POST', body: form }),
  downloadExport: async (artifact: ExportArtifact) => {
    const response = await fetchResponse(`/api/v1/exports/${artifact.id}/download`)
    if (!response.ok) {
      let body: ApiErrorBody = { code: 'DOWNLOAD_FAILED', message: `下载失败（${response.status}）` }
      try { body = await response.json() as ApiErrorBody } catch { /* keep stable fallback */ }
      throw new ApiError(body.code, body.message, response.status, body.details)
    }
    const blob = await response.blob()
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = artifact.filename
    anchor.click()
    URL.revokeObjectURL(href)
  },
}
