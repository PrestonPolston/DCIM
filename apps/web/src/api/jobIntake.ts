// Job intake v1 adapter (docs/design/job-intake.md, docs/db/JOB_INTAKE.md).
// Contract: /workspace/dcim-phone-audit/job-intake-v1/PROPOSED_JOB_INTAKE_API.md
// — proposal only; the built API wins when Backend ships it. JOB_INTAKE_API.live
// defaults to true; tests flip it off and use the in-memory mock of the same shapes.
import { ApiError, API_BASE_URL, getCsrfToken, listPage, request } from './client'
import { errorDetail, friendlyMessage, type ExistingJobRef } from './errors'
import { parseApiDate } from '../lib/apiDate'
import { createMockJobIntakeApi } from './jobIntake.mock'

export const JOB_INTAKE_API = {
  /** true = real /jobs endpoints; false = in-memory mock (tests set this; see src/test/setup.ts). */
  live: true,
}

export const DCREQ_PATTERN = /^DCREQ000[0-9]{4}$/
export const DCREQ_HINT = 'DCREQ000 + 4 digits'
export const JOB_OVERDUE_DAYS = 30
export const JOB_INTAKE_MAX_FILE_BYTES = 8 * 1024 * 1024

export type JobStatus = 'open' | 'closed'
export type ImportKind = 'epif' | 'cable_matrix'
export type ImportStatus = 'review' | 'committed' | 'abandoned'
export type ImportRowResult = 'ready' | 'warning' | 'held' | 'conflict' | 'committed' | 'skipped'

export type OpenItemType =
  | 'missing_hostname'
  | 'missing_profile'
  | 'profile_not_usable'
  | 'unresolved_cabinet'
  | 'missing_position'
  | 'missing_serial'
  | 'missing_psu'
  | 'psu_unparsed'
  | 'pdu_missing'
  | 'missing_port'
  | 'unresolved_hop'
  | 'missing_cable_label'
  | 'missing_trail'
  | 'epif_not_uploaded'
  | 'cable_matrix_not_uploaded'
  | 'space_power_flag'
  | 'media_missing'
  | 'ip_missing'
  | 'other'

export type OpenItemStatus = 'open' | 'deferred' | 'resolved' | 'dismissed'
export type OpenItemSource = 'epif' | 'cable_matrix' | 'manual'
export type OpenItemListStatus = OpenItemStatus | 'unresolved' | 'all'

export interface Job {
  id: number
  name: string
  dcreq: string
  primary_dcreq_id: number
  status: JobStatus
  opened_at: string
  closed_at: string | null
  closed_by: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  current: boolean
  overdue: boolean
  days_open: number
  recently_closed: boolean
  days_since_closed: number | null
  unresolved_count: number
  deferred_count: number
  device_count: number
  connection_count: number
}

export interface JobListParams {
  status?: JobStatus
  q?: string
  overdue?: boolean
  recently_closed?: boolean
  limit?: number
  offset?: number
}

export interface CloseWarning {
  code: 'job_has_open_items'
  message: string
  unresolved_count: number
}

export interface CloseJobResult {
  job: Job
  warning: CloseWarning | null
}

export interface RowMessage {
  code: string
  field: string | null
  message: string
}

export interface ImportRow {
  id: number
  row_number: number
  result: ImportRowResult
  messages: RowMessage[]
  hostname: string | null
  label: string | null
}

export interface ImportCounts {
  total: number
  ready: number
  warning: number
  held: number
  conflict: number
}

export interface JobImport {
  id: number
  job_id: number
  dcreq: string
  kind: ImportKind
  filename: string
  sha256: string
  status: ImportStatus
  uploaded_at: string
  uploaded_by: string | null
  counts: ImportCounts
  rows: ImportRow[]
}

export interface JobOpenItem {
  id: number
  job_id: number
  dcreq: string
  item_type: OpenItemType
  status: OpenItemStatus
  target_field: string | null
  note: string | null
  source: OpenItemSource
  epif_request_id: number | null
  device_id: number | null
  device_psu_assignment_id: number | null
  connection_id: number | null
  cable_id: number | null
  import_row_id: number | null
  filename: string | null
  hostname: string | null
  cable_label: string | null
  trail: string | null
  created_at: string
  created_by: string | null
  deferred_at: string | null
  deferred_by: string | null
  resolved_at: string | null
  resolved_by: string | null
}

export interface IntakePreview {
  job: Job
  epif: JobImport | null
  cable_matrix: JobImport | null
  skipped: { epif: boolean; cable_matrix: boolean }
  pending_items: JobOpenItem[]
}

export interface SkippedConflictRow {
  import_id: number
  kind: ImportKind
  row_number: number
  hostname: string | null
  label: string | null
  messages: RowMessage[]
}

export interface IntakeWarning {
  code: string
  message: string
  item_type?: string
  target_field?: string
  row_number?: number
  hostname?: string
}

export interface IntakeCommitResult {
  job: Job
  imports: JobImport[]
  warnings: IntakeWarning[]
  skipped_conflicts: SkippedConflictRow[]
  open_item_count: number
  items: JobOpenItem[]
}

export interface SkipFileResult {
  kind: ImportKind
  item_type: 'epif_not_uploaded' | 'cable_matrix_not_uploaded'
}

export interface JobIntakeApi {
  createJob(dcreq: string): Promise<Job>
  getJob(idOrDcreq: number | string): Promise<Job>
  listJobs(params?: JobListParams): Promise<{ items: Job[]; total: number }>
  closeJob(id: number): Promise<CloseJobResult>
  reopenJob(id: number): Promise<Job>
  abandonJob(id: number): Promise<void>
  stageImport(jobId: number, kind: ImportKind, file: File): Promise<JobImport>
  skipFile(jobId: number, kind: ImportKind): Promise<SkipFileResult>
  previewJob(jobId: number): Promise<IntakePreview>
  commitIntake(jobId: number): Promise<IntakeCommitResult>
  listOpenItems(jobId: number, status?: OpenItemListStatus): Promise<{ items: JobOpenItem[]; total: number }>
  deferItem(jobId: number, itemId: number, note?: string | null): Promise<JobOpenItem>
  undeferItem(jobId: number, itemId: number): Promise<JobOpenItem>
  dismissItem(jobId: number, itemId: number, note: string): Promise<JobOpenItem>
  resolveItem(jobId: number, itemId: number): Promise<JobOpenItem>
}

/** Trim, strip spaces, uppercase; rebuild a paste of the full id, 000XXXX, or the last 4 digits. */
export function normalizeDcreq(raw: string): string {
  const s = raw.trim().toUpperCase().replace(/\s+/g, '')
  if (DCREQ_PATTERN.test(s)) return s
  if (/^000[0-9]{4}$/.test(s)) return `DCREQ${s}`
  if (/^[0-9]{7}$/.test(s) && s.startsWith('000')) return `DCREQ${s}`
  if (/^[0-9]{4}$/.test(s)) return `DCREQ000${s}`
  return s
}

export function isValidDcreq(raw: string): boolean {
  return DCREQ_PATTERN.test(normalizeDcreq(raw))
}

const DAY_MS = 86_400_000

export function daysBetween(iso: string | null | undefined, now = Date.now()): number | null {
  const d = parseApiDate(iso)
  return d ? Math.floor((now - d.getTime()) / DAY_MS) : null
}

/** Strictly more than JOB_OVERDUE_DAYS, matching opened_at < now - 30 days. */
export function isJobOverdue(job: Pick<Job, 'status' | 'opened_at'>, now = Date.now()): boolean {
  if (job.status !== 'open') return false
  const opened = parseApiDate(job.opened_at)
  if (!opened) return false
  return opened.getTime() < now - JOB_OVERDUE_DAYS * DAY_MS
}

export function isDuplicateDcreq(e: unknown): e is ApiError {
  return e instanceof ApiError && e.status === 409 && (e.code === 'duplicate_dcreq' || e.code === 'job_exists')
}

export function duplicateExisting(e: unknown): ExistingJobRef | null {
  if (!isDuplicateDcreq(e)) return null
  return errorDetail(e.detail)?.existing ?? null
}

export function jobHref(job: Pick<Job, 'id' | 'dcreq'>): string {
  return `/jobs/${encodeURIComponent(job.dcreq)}`
}

function liveApi(): JobIntakeApi {
  return {
    createJob: (dcreq) => request<Job>('/jobs', { method: 'POST', body: JSON.stringify({ dcreq: normalizeDcreq(dcreq) }) }),
    getJob: (idOrDcreq) => request<Job>(`/jobs/${encodeURIComponent(String(idOrDcreq))}`),
    listJobs: (params = {}) => listPage<Job>('/jobs', params),
    closeJob: (id) => request<CloseJobResult>(`/jobs/${id}/close`, { method: 'POST' }),
    reopenJob: async (id) => {
      const res = await request<Job | { job: Job }>(`/jobs/${id}/reopen`, { method: 'POST' })
      return 'job' in res ? res.job : res
    },
    abandonJob: (id) => request<void>(`/jobs/${id}`, { method: 'DELETE' }),
    async stageImport(jobId, kind, file) {
      const form = new FormData()
      form.append('kind', kind)
      form.append('file', file)
      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/imports`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          ...(getCsrfToken() ? { 'X-CSRF-Token': getCsrfToken()! } : {}),
        },
        body: form,
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => undefined)
        const d = errorDetail(detail)
        const msg = d && friendlyMessage(d, res.status)
        const raw = (detail as { detail?: unknown } | undefined)?.detail
        const fallback =
          msg
          ?? (typeof raw === 'string' ? raw : undefined)
          ?? (raw && typeof raw === 'object' && !Array.isArray(raw) && typeof (raw as { message?: unknown }).message === 'string'
            ? (raw as { message: string }).message
            : `${res.status} ${res.statusText}`.trim())
        throw new ApiError(res.status, res.status === 403 ? `Not allowed: ${fallback}` : fallback, detail)
      }
      return (await res.json()) as JobImport
    },
    skipFile: (jobId, kind) =>
      request<SkipFileResult>(`/jobs/${jobId}/imports/skip`, { method: 'POST', body: JSON.stringify({ kind }) }),
    previewJob: (jobId) => request<IntakePreview>(`/jobs/${jobId}/preview`),
    commitIntake: (jobId) => request<IntakeCommitResult>(`/jobs/${jobId}/commit`, { method: 'POST' }),
    listOpenItems: (jobId, status = 'unresolved') => listPage<JobOpenItem>(`/jobs/${jobId}/open-items`, { status }),
    deferItem: (jobId, itemId, note = null) =>
      request<JobOpenItem>(`/jobs/${jobId}/open-items/${itemId}/defer`, { method: 'POST', body: JSON.stringify({ note }) }),
    undeferItem: (jobId, itemId) =>
      request<JobOpenItem>(`/jobs/${jobId}/open-items/${itemId}/undefer`, { method: 'POST' }),
    dismissItem: (jobId, itemId, note) =>
      request<JobOpenItem>(`/jobs/${jobId}/open-items/${itemId}/dismiss`, { method: 'POST', body: JSON.stringify({ note }) }),
    resolveItem: (jobId, itemId) =>
      request<JobOpenItem>(`/jobs/${jobId}/open-items/${itemId}/resolve`, { method: 'POST' }),
  }
}

let mock = createMockJobIntakeApi()

export function resetJobIntakeMock(): void {
  mock = createMockJobIntakeApi()
}

export function jobIntakeApi(): JobIntakeApi {
  return JOB_INTAKE_API.live ? liveApi() : mock
}

