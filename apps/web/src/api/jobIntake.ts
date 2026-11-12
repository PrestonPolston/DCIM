// Job intake v1 adapter (docs/design/job-intake.md, docs/db/JOB_INTAKE.md).
// Built API (Backend feat/job-intake-api @ bbff5fe, slice 1): POST/GET /jobs,
// GET /jobs/{id_or_dcreq}, POST .../close (acknowledge_open_items), POST .../reopen,
// GET .../open-items. Duplicate code is job_exists. Lists are arrays + X-Total-Count.
// Import, skip, preview, commit, DELETE abandon, and open-item writes are not shipped yet.
import { ApiError, API_BASE_URL, getCsrfToken, listPage, request } from './client'
import { errorDetail, friendlyMessage, type ExistingJobRef } from './errors'
import { parseApiDate } from '../lib/apiDate'
import { createMockJobIntakeApi } from './jobIntake.mock'

export const JOB_INTAKE_API = {
  /** true = real /jobs endpoints; false = in-memory mock (tests and VITE_JOB_INTAKE_LIVE=false). */
  live: import.meta.env.VITE_JOB_INTAKE_LIVE !== 'false',
  /** true = POST defer/undefer/dismiss/resolve/fill. Off until Backend ships those routes. */
  openItemWrites: import.meta.env.VITE_JOB_INTAKE_ITEM_WRITES === 'true',
  /** true = POST /imports, preview, commit. Off until Backend ships those routes. */
  imports: import.meta.env.VITE_JOB_INTAKE_IMPORTS === 'true',
}

/** Live API is on, but open-item write routes are not shipped yet. */
export function jobItemWritesAvailable(): boolean {
  return !JOB_INTAKE_API.live || JOB_INTAKE_API.openItemWrites
}

/** Live API is on, but import/preview/commit routes are not shipped yet. */
export function jobImportsAvailable(): boolean {
  return !JOB_INTAKE_API.live || JOB_INTAKE_API.imports
}

export const DCREQ_PATTERN = /^DCREQ000[0-9]{4}$/
export const DCREQ_HINT = 'DCREQ000 + 4 digits'
export const JOB_OVERDUE_DAYS = 30
export const JOB_INTAKE_MAX_FILE_BYTES = 8 * 1024 * 1024

export type JobStatus = 'open' | 'closed'
export type ImportKind = 'epif' | 'cable_matrix'
export type ImportStatus = 'review' | 'committed' | 'abandoned'
export type ImportRowResult = 'ready' | 'warning' | 'held' | 'conflict' | 'committed' | 'skipped'

/** PSU columns become open items (missing_psu / psu_unparsed). unresolved_hop is used once p1_34 lands. */
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
  description?: string | null
  site_id?: number | null
  status: JobStatus
  opened_at: string
  closed_at: string | null
  closed_by: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  current: boolean
  overdue: boolean
  /** opened_at + 30 days (UTC Z). Present on the committed /jobs contract. */
  overdue_at?: string
  days_open: number
  recently_closed: boolean
  days_since_closed: number | null
  unresolved_count: number
  deferred_count: number
  device_count: number
  /** Mock and later slices; Backend slice 1 (bbff5fe) does not return this yet. */
  connection_count: number
  /** Detail only (GET /jobs/{key} and POST /jobs). */
  unresolved_by_type?: Record<string, number>
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
  /** Mock Fill: the value written to target_field before resolve. */
  filled_value?: string | null
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

export interface JobIntakeApi {
  createJob(dcreq: string): Promise<Job>
  getJob(idOrDcreq: number | string): Promise<Job>
  listJobs(params?: JobListParams): Promise<{ items: Job[]; total: number }>
  closeJob(id: number, opts?: { acknowledge_open_items?: boolean; note?: string | null }): Promise<CloseJobResult>
  reopenJob(id: number, note?: string | null): Promise<Job>
  abandonJob(id: number): Promise<void>
  stageImport(jobId: number, kind: ImportKind, file: File): Promise<JobImport>
  previewJob(jobId: number): Promise<IntakePreview>
  /** POST /jobs/{id}/imports/{import_id}/commit — one batch still in review. */
  commitImport(jobId: number, importId: number): Promise<IntakeCommitResult>
  /** POST /jobs/{id}/commit — every batch still in review. */
  commitIntake(jobId: number): Promise<IntakeCommitResult>
  listOpenItems(jobId: number, status?: OpenItemListStatus): Promise<{ items: JobOpenItem[]; total: number }>
  deferItem(jobId: number, itemId: number, note?: string | null): Promise<JobOpenItem>
  undeferItem(jobId: number, itemId: number): Promise<JobOpenItem>
  dismissItem(jobId: number, itemId: number, note: string): Promise<JobOpenItem>
  resolveItem(jobId: number, itemId: number): Promise<JobOpenItem>
  /** Write a value for target_field, then mark the item resolved (mock; live when writes ship). */
  fillItem(jobId: number, itemId: number, value: string): Promise<JobOpenItem>
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

/** opened_at + 30 days (UTC Z), the committed `overdue_at` field. */
export function jobOverdueAt(openedAt: string | null | undefined): string | undefined {
  const opened = parseApiDate(openedAt)
  if (!opened) return undefined
  return new Date(opened.getTime() + JOB_OVERDUE_DAYS * DAY_MS).toISOString()
}

/**
 * Open more than 30 days. Prefers `overdue_at` (opened_at + 30 days) when present;
 * otherwise opened_at < now - 30 days. Closed jobs are never overdue.
 */
export function isJobOverdue(job: Pick<Job, 'status' | 'opened_at'> & { overdue_at?: string }, now = Date.now()): boolean {
  if (job.status !== 'open') return false
  const dueIso = job.overdue_at ?? jobOverdueAt(job.opened_at)
  const due = parseApiDate(dueIso)
  return !!due && due.getTime() < now
}

export function isDuplicateDcreq(e: unknown): e is ApiError {
  return e instanceof ApiError && e.status === 409 && (e.code === 'duplicate_dcreq' || e.code === 'job_exists')
}

export function isJobHasOpenItems(e: unknown): e is ApiError {
  return e instanceof ApiError && e.status === 409 && e.code === 'job_has_open_items'
}

export function closeOpenItemsWarning(e: unknown): CloseWarning | null {
  if (!isJobHasOpenItems(e)) return null
  const d = errorDetail(e.detail) ?? { code: 'job_has_open_items' }
  const count = d.unresolved_count ?? 0
  return {
    code: 'job_has_open_items',
    message: friendlyMessage({ ...d, code: 'job_has_open_items', unresolved_count: count }, 409)
      ?? 'This job still has unresolved items. You can close it anyway.',
    unresolved_count: count,
  }
}

export function matchesOpenItemFilter(status: OpenItemStatus, filter: OpenItemListStatus): boolean {
  if (filter === 'all') return true
  if (filter === 'unresolved') return status === 'open' || status === 'deferred'
  return status === filter
}

const ITEM_TYPE_LABELS: Record<string, string> = {
  missing_hostname: 'Missing hostname',
  missing_profile: 'Missing profile',
  profile_not_usable: 'Profile not usable',
  unresolved_cabinet: 'Unresolved cabinet',
  missing_position: 'Missing position',
  missing_serial: 'Missing serial',
  missing_psu: 'Missing PSU',
  psu_unparsed: 'PSU not parsed',
  pdu_missing: 'Missing PDU',
  missing_port: 'Missing port',
  unresolved_hop: 'Unresolved hop',
  missing_cable_label: 'Missing cable label',
  missing_trail: 'Missing trail',
  epif_not_uploaded: 'ePIF not uploaded',
  cable_matrix_not_uploaded: 'Cable matrix not uploaded',
  space_power_flag: 'Space and power flag',
  media_missing: 'Missing media',
  ip_missing: 'Missing IP',
  other: 'Other',
}

export function itemTypeLabel(type: string): string {
  if (ITEM_TYPE_LABELS[type]) return ITEM_TYPE_LABELS[type]
  const spaced = type.replaceAll('_', ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** @deprecated use itemTypeLabel */
export function humanizeItemType(type: string): string {
  return itemTypeLabel(type)
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
    closeJob: (id, opts = {}) =>
      request<CloseJobResult>(`/jobs/${id}/close`, {
        method: 'POST',
        body: JSON.stringify({
          acknowledge_open_items: opts.acknowledge_open_items ?? false,
          note: opts.note ?? null,
        }),
      }),
    reopenJob: async (id, note = null) => {
      const res = await request<Job | { job: Job }>(`/jobs/${id}/reopen`, {
        method: 'POST',
        body: JSON.stringify({ note }),
      })
      return 'job' in res ? res.job : res
    },
    // DELETE /jobs/{id} (abandon) is not in the committed API. The wizard must not call this when live.
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
    previewJob: (jobId) => request<IntakePreview>(`/jobs/${jobId}/preview`),
    commitImport: (jobId, importId) =>
      request<IntakeCommitResult>(`/jobs/${jobId}/imports/${importId}/commit`, { method: 'POST' }),
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
    fillItem: (jobId, itemId, value) =>
      request<JobOpenItem>(`/jobs/${jobId}/open-items/${itemId}/fill`, { method: 'POST', body: JSON.stringify({ value }) }),
  }
}

let mock = createMockJobIntakeApi()

export function resetJobIntakeMock(): void {
  mock = createMockJobIntakeApi()
}

export function jobIntakeApi(): JobIntakeApi {
  return JOB_INTAKE_API.live ? liveApi() : mock
}
