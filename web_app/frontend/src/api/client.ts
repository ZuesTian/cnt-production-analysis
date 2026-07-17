import type {
  ApiErrorBody,
  DatasetSummary,
  ExportArtifact,
  FilterOptions,
  JobStatus,
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

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: options?.body instanceof FormData ? options.headers : { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
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
}
