import type { components } from './openapi.gen'

export type Grain = NonNullable<components['schemas']['FilterScope']['grain']>
export type Severity = components['schemas']['QualityIssueBody']['severity']
type GeneratedDatasetSummary = components['schemas']['DatasetSummary']
type GeneratedQualityIssue = components['schemas']['QualityIssueBody']
type GeneratedJobStatus = components['schemas']['JobStatus']

export interface DatasetSummary extends Omit<GeneratedDatasetSummary, 'published_at' | 'expires_at' | 'date_min' | 'date_max' | 'complete_dates' | 'coverage'> {
  published_at: string | null
  expires_at: string | null
  date_min: string | null
  date_max: string | null
  complete_dates: Record<string, string>
  coverage: Record<string, CoverageDetail>
}

export interface CoverageDetail {
  date_min: string
  date_max: string
  suggested_complete_date: string
  suggested_verified: boolean
  suggested_row_count: number
  suggested_coverage_ratio: number
  latest_row_count: number
  latest_coverage_ratio: number
  date_count: number
}

export interface QualityIssue extends Omit<GeneratedQualityIssue, 'details'> {
  details: Record<string, unknown>
}

export interface QualityReport { dataset: DatasetSummary; issues: QualityIssue[] }

export interface KpiValue {
  key: string
  label: string
  value: number | null
  unit: string
  previous_value: number | null
  delta_percent: number | null
}

export interface LineSnapshot {
  production_line: string
  snapshot_date: string
  is_confirmed_complete: boolean
  kpis: KpiValue[]
  active_furnaces: number
  serious_alerts: number
  pairing_completeness: number
  freshness_days: number
}

export interface OverviewResponse {
  dataset: DatasetSummary
  line_snapshots: LineSnapshot[]
  common_comparison_date: string | null
  quality_issue_counts: Record<string, number>
  top_risks: QualityIssue[]
}

export interface SeriesResponse {
  grain: Grain | string
  rows: Record<string, unknown>[]
  metadata: Record<string, unknown>
}

export interface FilterOptions {
  dataset: DatasetSummary
  production_lines: string[]
  furnaces: string[]
  furnaces_by_line: Record<string, string[]>
  date_min: string | null
  date_max: string | null
  complete_dates: Record<string, string>
}

export interface JobStatus extends Omit<GeneratedJobStatus, 'status' | 'dataset_id' | 'result' | 'error_code' | 'error_detail' | 'started_at' | 'finished_at'> {
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  dataset_id: string | null
  result: Record<string, unknown>
  error_code: string | null
  error_detail: string | null
  started_at: string | null
  finished_at: string | null
}

export interface ExportArtifact {
  id: string
  dataset_id: string
  report_type: string
  filename: string
  size: number
  created_at: string
}

export interface ApiErrorBody { code: string; message: string; details?: unknown }

export interface AuthUser {
  username: string
  display_name: string
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: AuthUser
}

export interface PasteImportPayload {
  kind: 'shared' | 'temporary'
  name: string
  content: string
}
