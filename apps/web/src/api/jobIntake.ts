// Job intake v1 adapter (docs/design/job-intake.md, docs/db/JOB_INTAKE.md).
// Built API (Backend feat/job-intake-api @ c1ed7db, slices 1–3): POST/GET /jobs,
// close/reopen, open-items read + defer/undefer/dismiss/resolve, ePIF and
// cable-matrix POST /imports (raw text/csv, kind=epif|cable_matrix), GET import
// detail (the preview), commit. No /fill, no DELETE abandon yet. /connections
// does not expose hops, IP config or status; this client does not read those.
import { ApiError, API_BASE_URL, getCsrfToken, listPage, request } from './client'
import { errorDetail, friendlyMessage, type ExistingJobRef } from './errors'
import { parseApiDate } from '../lib/apiDate'
import { createMockJobIntakeApi } from './jobIntake.mock'

export const JOB_INTAKE_API = {
  /** true = real /jobs endpoints; false = in-memory mock (tests and VITE_JOB_INTAKE_LIVE=false). */
  live: import.meta.env.VITE_JOB_INTAKE_LIVE !== 'false',
  /** true = POST defer/undefer/dismiss/resolve (slice 2). Set to 'false' to disable. */
  openItemWrites: import.meta.env.VITE_JOB_INTAKE_ITEM_WRITES !== 'false',
  /** true = ePIF POST /imports and commit (slice 2). Set to 'false' to disable. */
  imports: import.meta.env.VITE_JOB_INTAKE_IMPORTS !== 'false',
  /** true = cable-matrix POST /imports (slice 3). Set to 'false' to disable. */
  cableImports: import.meta.env.VITE_JOB_INTAKE_CABLE_IMPORTS !== 'false',
}

/** Live API is on, but open-item write routes are not shipped yet. */
export function jobItemWritesAvailable(): boolean {
  return !JOB_INTAKE_API.live || JOB_INTAKE_API.openItemWrites
}

/** Live API is on, but import/preview/commit routes are not shipped yet. */
export function jobImportsAvailable(): boolean {
  return !JOB_INTAKE_API.live || JOB_INTAKE_API.imports
}

/** Live API is on, but cable-matrix import is disabled. */
export function jobCableImportsAvailable(): boolean {
  return !JOB_INTAKE_API.live || JOB_INTAKE_API.cableImports
}

/** Fill is available whenever open-item writes are: mock writes the field, live resolves with a note. */
export function jobFillAvailable(): boolean {
  return jobItemWritesAvailable()
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
  /** Non-removed connections whose cable has project_id = this job (slice 3). */
  connection_count?: number
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
  level?: 'conflict' | 'held' | 'warning' | 'info'
  item_type?: string | null
  target_field?: string | null
}

export interface ImportRow {
  id: number
  row_number: number
  result: ImportRowResult
  messages: RowMessage[]
  hostname: string | null
  label?: string | null
  epif_id?: string | null
  rack?: string | null
  ru?: string | null
  /** Cable-matrix row fields (slice 3). */
  matrix_id?: string | null
  a?: string | null
  z?: string | null
  trail?: string | null
  cable_label?: string | null
  connection_id?: number | null
  cable_id?: number | null
}

export interface ImportCounts {
  total: number
  ready: number
  warning: number
  held: number
  conflict: number
  committed?: number
  skipped?: number
}

export interface JobImport {
  id: number
  job_id: number
  dcreq: string
  kind: ImportKind
  filename: string | null
  sha256: string
  status: ImportStatus
  uploaded_at: string
  uploaded_by: string | null
  change_set_id?: number | null
  counts: ImportCounts
  reupload?: 'review' | 'committed' | null
  rows?: ImportRow[]
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
  epif_request_id?: number | null
  device_id: number | null
  device_psu_assignment_id?: number | null
  connection_id: number | null
  cable_id: number | null
  import_row_id: number | null
  filename: string | null
  hostname: string | null
  cable_label: string | null
  /** Joined at read time from the item's cable, else its connection's cable (slice 3). */
  cable_trail?: string | null
  /** @deprecated use cable_trail */
  trail?: string | null
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
  matrix_id?: string | null
  a?: string | null
  z?: string | null
  cable_label?: string | null
}

/** committed[] / held[] / skipped[] row on CommitResult (ePIF and cable-matrix). */
export interface CommitRow {
  import_id: number
  kind: ImportKind
  row_number: number
  hostname?: string | null
  epif_id?: string | null
  device_id?: number | null
  epif_request_id?: number | null
  matrix_id?: string | null
  a?: string | null
  z?: string | null
  connection_id?: number | null
  cable_id?: number | null
  cable_label?: string | null
  reasons?: RowMessage[]
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
  committed: CommitRow[]
  held: CommitRow[]
  skipped_conflicts: SkippedConflictRow[]
  open_item_count: number
  items: JobOpenItem[]
}

export interface OpenItemWriteResult {
  item: JobOpenItem
  job: Job
}

export interface JobIntakeApi {
  createJob(dcreq: string, fields?: { name?: string | null; description?: string | null }): Promise<Job>
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
  deferItem(jobId: number, itemId: number, note?: string | null): Promise<OpenItemWriteResult>
  undeferItem(jobId: number, itemId: number): Promise<OpenItemWriteResult>
  dismissItem(jobId: number, itemId: number, note: string): Promise<OpenItemWriteResult>
  resolveItem(jobId: number, itemId: number, note?: string | null): Promise<OpenItemWriteResult>
  /** Mock: write target_field then resolve. Live: POST resolve with the value as a note. */
  fillItem(jobId: number, itemId: number, value: string): Promise<OpenItemWriteResult>
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
  unresolved_device: 'Unresolved device',
  missing_cable_label: 'Missing cable label',
  missing_trail: 'Missing trail',
  epif_not_uploaded: 'ePIF not uploaded',
  cable_matrix_not_uploaded: 'Cable matrix not uploaded',
  space_power_flag: 'Space and power flag',
  media_missing: 'Missing media',
  ip_missing: 'Missing IP',
  port_in_use: 'Port in use',
  hop_in_use: 'Hop in use',
  cable_label_conflict: 'Cable label conflict',
  other: 'Other',
}

export function itemTypeLabel(type: string): string {
  if (ITEM_TYPE_LABELS[type]) return ITEM_TYPE_LABELS[type]
  const spaced = type.replaceAll('_', ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

const FIELD_LABELS: Record<string, string> = {
  position_u: 'position (U)',
  rack_id: 'cabinet',
  psu_1: 'PSU 1',
  psu_2: 'PSU 2',
  host_name: 'hostname',
  hostname: 'hostname',
  serial_number: 'serial number',
  profile_id: 'profile',
  device_type_id: 'profile',
  airflow: 'airflow',
  face: 'face',
  status: 'status',
  asset_tag: 'asset tag',
  managed_by: 'managed by',
  app_service: 'app service',
  host_name_a: 'A hostname',
  host_name_z: 'Z hostname',
  port_a: 'A port',
  port_z: 'Z port',
  rack_a: 'A cabinet',
  rack_z: 'Z cabinet',
  hop_1: 'hop 1',
  hop_2: 'hop 2',
  hop_3: 'hop 3',
  hop_4: 'hop 4',
  hop_5: 'hop 5',
  hop_6: 'hop 6',
  hop_7: 'hop 7',
  label: 'cable label',
  cable_label: 'cable label',
  trail: 'trail',
  media: 'media',
  speed_a: 'A speed',
  speed_z: 'Z speed',
  ip_address: 'IP address',
  vlan: 'VLAN',
}

export function fieldLabel(field: string): string {
  if (FIELD_LABELS[field]) return FIELD_LABELS[field]
  return field.replaceAll('_', ' ')
}

export function countLabel(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`
}

export function devicePageHref(item: Pick<JobOpenItem, 'device_id' | 'hostname'>): string | null {
  if (item.device_id == null) return null
  if (item.hostname) return `/devices?q=${encodeURIComponent(item.hostname)}`
  return '/devices'
}

export function cableTrail(item: Pick<JobOpenItem, 'cable_trail' | 'trail'>): string | null {
  return item.cable_trail ?? item.trail ?? null
}

export function normalizeOpenItem(item: JobOpenItem): JobOpenItem {
  return { ...item, cable_trail: item.cable_trail ?? item.trail ?? null }
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

async function writeOpenItem(path: string, body?: unknown): Promise<OpenItemWriteResult> {
  const res = await request<OpenItemWriteResult | JobOpenItem>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res && typeof res === 'object' && 'item' in res) {
    const wrapped = res as OpenItemWriteResult
    return { item: normalizeOpenItem(wrapped.item), job: wrapped.job }
  }
  return { item: normalizeOpenItem(res as JobOpenItem), job: await request<Job>(`/jobs/${(res as JobOpenItem).job_id}`) }
}

type LiveSkipped = CommitRow & {
  hostname?: string | null
  epif_id?: string | null
  reasons?: RowMessage[]
  messages?: RowMessage[]
}

type LiveCommit = {
  job: Job
  imports: JobImport[]
  committed?: CommitRow[]
  held?: CommitRow[]
  skipped?: LiveSkipped[]
  skipped_conflicts?: SkippedConflictRow[]
  warnings: IntakeWarning[]
  open_item_count: number
}

function toSkippedConflict(row: LiveSkipped): SkippedConflictRow {
  return {
    import_id: row.import_id,
    kind: row.kind,
    row_number: row.row_number,
    hostname: row.hostname ?? null,
    label: row.cable_label ?? row.epif_id ?? null,
    messages: row.messages ?? row.reasons ?? [],
    matrix_id: row.matrix_id ?? null,
    a: row.a ?? null,
    z: row.z ?? null,
    cable_label: row.cable_label ?? null,
  }
}

async function normalizeLiveCommit(jobId: number, raw: LiveCommit): Promise<IntakeCommitResult> {
  const page = await listPage<JobOpenItem>(`/jobs/${jobId}/open-items`, { status: 'unresolved' })
  const skipped = raw.skipped_conflicts ?? (raw.skipped ?? []).map(toSkippedConflict)
  return {
    job: raw.job,
    imports: raw.imports,
    warnings: raw.warnings,
    committed: raw.committed ?? [],
    held: raw.held ?? [],
    skipped_conflicts: skipped,
    open_item_count: raw.open_item_count,
    items: page.items.map(normalizeOpenItem),
  }
}

function pendingFromImport(imp: JobImport): JobOpenItem[] {
  const rows = imp.rows ?? []
  const pending: JobOpenItem[] = []
  for (const row of rows) {
    for (const msg of row.messages) {
      if (!msg.item_type) continue
      if (row.result !== 'warning' && row.result !== 'held' && row.result !== 'conflict') continue
      pending.push({
        id: -(row.id * 100 + pending.length + 1),
        job_id: imp.job_id,
        dcreq: imp.dcreq,
        item_type: msg.item_type as OpenItemType,
        status: 'open',
        target_field: msg.target_field ?? null,
        note: msg.message,
        source: imp.kind,
        epif_request_id: null,
        device_id: null,
        device_psu_assignment_id: null,
        connection_id: null,
        cable_id: null,
        import_row_id: row.id,
        filename: imp.filename,
        hostname: row.hostname,
        cable_label: row.cable_label ?? row.label ?? null,
        cable_trail: row.trail ?? null,
        trail: row.trail ?? null,
        created_at: imp.uploaded_at,
        created_by: imp.uploaded_by,
        deferred_at: null,
        deferred_by: null,
        resolved_at: null,
        resolved_by: null,
      })
    }
  }
  return pending
}

function liveApi(): JobIntakeApi {
  return {
    createJob: (dcreq, fields) => request<Job>('/jobs', {
      method: 'POST',
      body: JSON.stringify({
        dcreq,
        ...(fields?.name != null && fields.name !== '' ? { name: fields.name } : {}),
        ...(fields?.description != null && fields.description !== '' ? { description: fields.description } : {}),
      }),
    }),
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
      const qs = new URLSearchParams({ kind, filename: file.name })
      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/imports?${qs}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'text/csv',
          ...(getCsrfToken() ? { 'X-CSRF-Token': getCsrfToken()! } : {}),
        },
        body: await file.text(),
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
    async previewJob(jobId) {
      const staged = await listPage<JobImport>(`/jobs/${jobId}/imports`, { status: 'review' })
      const details = await Promise.all(
        staged.items.map((imp) => request<JobImport>(`/jobs/${jobId}/imports/${imp.id}`)),
      )
      const epif = details.find((i) => i.kind === 'epif') ?? null
      const cable = details.find((i) => i.kind === 'cable_matrix') ?? null
      const job = await request<Job>(`/jobs/${jobId}`)
      const open = await listPage<JobOpenItem>(`/jobs/${jobId}/open-items`, { status: 'unresolved' })
      const existing = open.items.map(normalizeOpenItem).filter((item) => {
        if (epif && item.item_type === 'epif_not_uploaded') return false
        if (cable && item.item_type === 'cable_matrix_not_uploaded') return false
        return true
      })
      const fromFiles = details.flatMap(pendingFromImport)
      return {
        job,
        epif,
        cable_matrix: cable,
        skipped: { epif: !epif, cable_matrix: !cable },
        pending_items: [...existing, ...fromFiles],
      }
    },
    async commitImport(jobId, importId) {
      const raw = await request<LiveCommit>(`/jobs/${jobId}/imports/${importId}/commit`, { method: 'POST' })
      return normalizeLiveCommit(jobId, raw)
    },
    async commitIntake(jobId) {
      const raw = await request<LiveCommit>(`/jobs/${jobId}/commit`, { method: 'POST' })
      return normalizeLiveCommit(jobId, raw)
    },
    async listOpenItems(jobId, status = 'unresolved') {
      const page = await listPage<JobOpenItem>(`/jobs/${jobId}/open-items`, { status })
      return { ...page, items: page.items.map(normalizeOpenItem) }
    },
    deferItem: (jobId, itemId, note = null) =>
      writeOpenItem(`/jobs/${jobId}/open-items/${itemId}/defer`, { note }),
    undeferItem: (jobId, itemId) =>
      writeOpenItem(`/jobs/${jobId}/open-items/${itemId}/undefer`),
    dismissItem: (jobId, itemId, note) =>
      writeOpenItem(`/jobs/${jobId}/open-items/${itemId}/dismiss`, { note }),
    resolveItem: (jobId, itemId, note = null) =>
      writeOpenItem(`/jobs/${jobId}/open-items/${itemId}/resolve`, note != null ? { note } : {}),
    fillItem: (jobId, itemId, value) =>
      writeOpenItem(`/jobs/${jobId}/open-items/${itemId}/resolve`, { note: value }),
  }
}

let mock = createMockJobIntakeApi()

export function resetJobIntakeMock(): void {
  mock = createMockJobIntakeApi()
}

export function jobIntakeApi(): JobIntakeApi {
  return JOB_INTAKE_API.live ? liveApi() : mock
}
