// In-memory job-intake mock that mirrors the proposed /jobs contract.
import { ApiError } from './client'
import {
  DCREQ_PATTERN,
  JOB_INTAKE_MAX_FILE_BYTES,
  JOB_OVERDUE_DAYS,
  daysBetween,
  isJobOverdue,
  isValidDcreq,
  jobOverdueAt,
  normalizeDcreq,
  type ImportKind,
  type ImportRow,
  type ImportRowResult,
  type IntakeCommitResult,
  type IntakeWarning,
  type Job,
  type JobImport,
  type JobIntakeApi,
  type JobListParams,
  type JobOpenItem,
  type OpenItemListStatus,
  type OpenItemStatus,
  type OpenItemType,
  type SkippedConflictRow,
} from './jobIntake'

const ACTOR = 'admin@demo.local'
const FORBIDDEN = /^(ilo\s*password|password|secret|ilo_password)$/i

type Store = {
  jobs: Job[]
  imports: JobImport[]
  skipped: { jobId: number; kind: ImportKind }[]
  items: JobOpenItem[]
  nextJob: number
  nextRef: number
  nextImport: number
  nextRow: number
  nextItem: number
}

let store: Store = empty()

function empty(): Store {
  return { jobs: [], imports: [], skipped: [], items: [], nextJob: 1, nextRef: 1, nextImport: 1, nextRow: 1, nextItem: 1 }
}

function iso(ms = Date.now()): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z')
}

function throwApi(status: number, code: string, message: string, extra: Record<string, unknown> = {}): never {
  throw new ApiError(status, message, { detail: { code, message, ...extra } })
}

function flags(job: Job, now = Date.now()): Job {
  const daysOpen = daysBetween(job.opened_at, now) ?? 0
  const daysSinceClosed = job.closed_at ? daysBetween(job.closed_at, now) : null
  const unresolved = store.items.filter((i) => i.job_id === job.id && (i.status === 'open' || i.status === 'deferred'))
  const current = job.status === 'open'
  return {
    ...job,
    current,
    overdue_at: job.overdue_at ?? jobOverdueAt(job.opened_at),
    overdue: isJobOverdue({ ...job, overdue_at: job.overdue_at ?? jobOverdueAt(job.opened_at) }, now),
    days_open: daysOpen,
    recently_closed: job.status === 'closed' && daysSinceClosed != null && daysSinceClosed <= JOB_OVERDUE_DAYS,
    days_since_closed: job.status === 'closed' ? daysSinceClosed : null,
    unresolved_count: unresolved.length,
    deferred_count: unresolved.filter((i) => i.status === 'deferred').length,
    unresolved_by_type: unresolved.reduce<Record<string, number>>((acc, i) => {
      acc[i.item_type] = (acc[i.item_type] ?? 0) + 1
      return acc
    }, {}),
  }
}

function findJob(idOrDcreq: number | string): Job {
  const key = String(idOrDcreq)
  const job = store.jobs.find((j) => String(j.id) === key || j.dcreq === normalizeDcreq(key) || j.dcreq === key)
  if (!job) throwApi(404, 'not_found', 'Job not found')
  return job
}

function getJobOrThrow(idOrDcreq: number | string): Job {
  return flags(findJob(idOrDcreq))
}

function existingRef(job: Job) {
  return { id: job.id, dcreq: job.dcreq, name: job.name, status: job.status, is_job: true, deleted: false }
}

function countsOf(rows: ImportRow[]) {
  return {
    total: rows.length,
    ready: rows.filter((r) => r.result === 'ready').length,
    warning: rows.filter((r) => r.result === 'warning').length,
    held: rows.filter((r) => r.result === 'held').length,
    conflict: rows.filter((r) => r.result === 'conflict').length,
  }
}

function parseCsv(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').filter((l) => l.length > 0)
  if (!lines.length) throwApi(422, 'validation', 'This file is empty or unreadable.')
  const headers = lines[0].split(',').map((h) => h.trim())
  const rows = lines.slice(1).map((l) => l.split(',').map((c) => c.trim()))
  return { headers, rows }
}

function col(headers: string[], cells: string[], ...names: string[]): string | null {
  const i = headers.findIndex((h) => names.some((n) => h.toLowerCase() === n.toLowerCase()))
  if (i < 0) return null
  const v = cells[i] ?? ''
  return v === '' ? null : v
}

function shaOf(text: string, filename: string): string {
  let h = 0
  const s = `${filename}:${text}`
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0
  return `mock-${(h >>> 0).toString(16)}`
}

function skipType(kind: ImportKind): 'epif_not_uploaded' | 'cable_matrix_not_uploaded' {
  return kind === 'epif' ? 'epif_not_uploaded' : 'cable_matrix_not_uploaded'
}

function addItem(partial: Omit<JobOpenItem, 'id' | 'created_at'> & { created_at?: string }): JobOpenItem {
  const existing = store.items.find((i) =>
    i.job_id === partial.job_id
    && i.item_type === partial.item_type
    && (i.target_field ?? '') === (partial.target_field ?? '')
    && (i.import_row_id ?? 0) === (partial.import_row_id ?? 0)
    && (i.device_id ?? 0) === (partial.device_id ?? 0)
    && (i.status === 'open' || i.status === 'deferred'),
  )
  if (existing) {
    Object.assign(existing, { note: partial.note ?? existing.note, import_row_id: partial.import_row_id ?? existing.import_row_id })
    return existing
  }
  const item: JobOpenItem = {
    ...partial,
    id: store.nextItem++,
    created_at: partial.created_at ?? iso(),
    epif_request_id: partial.epif_request_id ?? null,
    device_id: partial.device_id ?? null,
    device_psu_assignment_id: partial.device_psu_assignment_id ?? null,
    connection_id: partial.connection_id ?? null,
    cable_id: partial.cable_id ?? null,
    import_row_id: partial.import_row_id ?? null,
    filename: partial.filename ?? null,
    hostname: partial.hostname ?? null,
    cable_label: partial.cable_label ?? null,
    trail: partial.trail ?? null,
    note: partial.note ?? null,
    target_field: partial.target_field ?? null,
    created_by: partial.created_by ?? ACTOR,
    deferred_at: partial.deferred_at ?? null,
    deferred_by: partial.deferred_by ?? null,
    resolved_at: partial.resolved_at ?? null,
    resolved_by: partial.resolved_by ?? null,
  }
  store.items.push(item)
  return item
}

function getItem(jobId: number, itemId: number): JobOpenItem {
  const item = store.items.find((i) => i.id === itemId && i.job_id === jobId)
  if (!item) throwApi(404, 'not_found', 'Open item not found')
  return item
}

export function seedMockJob(init: Partial<Job> & { dcreq: string }): Job {
  const dcreq = normalizeDcreq(init.dcreq)
  const nowIso = init.opened_at ?? iso()
  const id = init.id ?? store.nextJob++
  if (init.id && init.id >= store.nextJob) store.nextJob = init.id + 1
  const job: Job = {
    id,
    name: init.name ?? dcreq,
    dcreq,
    primary_dcreq_id: init.primary_dcreq_id ?? store.nextRef++,
    status: init.status ?? 'open',
    opened_at: nowIso,
    closed_at: init.closed_at ?? null,
    closed_by: init.closed_by ?? null,
    created_at: init.created_at ?? nowIso,
    updated_at: init.updated_at ?? nowIso,
    created_by: init.created_by ?? ACTOR,
    current: true,
    overdue: false,
    days_open: 0,
    recently_closed: false,
    days_since_closed: null,
    unresolved_count: init.unresolved_count ?? 0,
    deferred_count: init.deferred_count ?? 0,
    device_count: init.device_count ?? 0,
    connection_count: init.connection_count ?? 0,
  }
  store.jobs.push(job)
  return flags(job)
}

export function seedMockOpenItem(init: Partial<JobOpenItem> & { job_id: number; item_type: OpenItemType }): JobOpenItem {
  const job = findJob(init.job_id)
  return addItem({
    job_id: job.id,
    dcreq: job.dcreq,
    item_type: init.item_type,
    status: init.status ?? 'open',
    target_field: init.target_field ?? null,
    note: init.note ?? null,
    source: init.source ?? 'manual',
    epif_request_id: init.epif_request_id ?? null,
    device_id: init.device_id ?? null,
    device_psu_assignment_id: init.device_psu_assignment_id ?? null,
    connection_id: init.connection_id ?? null,
    cable_id: init.cable_id ?? null,
    import_row_id: init.import_row_id ?? null,
    filename: init.filename ?? null,
    hostname: init.hostname ?? null,
    cable_label: init.cable_label ?? null,
    trail: init.trail ?? null,
    created_by: init.created_by ?? ACTOR,
    deferred_at: init.deferred_at ?? null,
    deferred_by: init.deferred_by ?? null,
    resolved_at: init.resolved_at ?? null,
    resolved_by: init.resolved_by ?? null,
  })
}


function resolveSkipItem(job: Job, kind: ImportKind) {
  const type = skipType(kind)
  const item = store.items.find((i) => i.job_id === job.id && i.item_type === type && (i.status === 'open' || i.status === 'deferred'))
  if (!item) return
  item.status = 'resolved'
  item.resolved_at = iso()
  item.resolved_by = ACTOR
}

function finalizeCommit(job: Job, batches: JobImport[]): IntakeCommitResult {
  const warnings: IntakeWarning[] = []
  const skipped_conflicts: SkippedConflictRow[] = []
  for (const batch of batches) {
    if (batch.status !== 'review') continue
    for (const row of batch.rows) {
      if (row.result === 'conflict') {
        skipped_conflicts.push({
          import_id: batch.id,
          kind: batch.kind,
          row_number: row.row_number,
          hostname: row.hostname,
          label: row.label,
          messages: row.messages,
        })
        addItem({
          job_id: job.id, dcreq: job.dcreq, item_type: 'other', status: 'open',
          target_field: row.messages[0]?.field ?? 'hostname', note: row.messages[0]?.message ?? null,
          source: batch.kind, import_row_id: row.id, filename: batch.filename, hostname: row.hostname,
          cable_label: row.label, trail: null, epif_request_id: null, device_id: null,
          device_psu_assignment_id: null, connection_id: null, cable_id: null,
          created_by: ACTOR, deferred_at: null, deferred_by: null, resolved_at: null, resolved_by: null,
        })
        row.result = 'skipped'
        continue
      }
      if (row.result === 'warning' || row.result === 'held') {
        const type = (row.messages[0]?.code as OpenItemType) || 'other'
        warnings.push({
          code: row.messages[0]?.code ?? 'warning',
          message: row.messages[0]?.message ?? 'This row has a warning.',
          item_type: type,
          target_field: row.messages[0]?.field ?? undefined,
          row_number: row.row_number,
          hostname: row.hostname ?? undefined,
        })
        addItem({
          job_id: job.id, dcreq: job.dcreq, item_type: type, status: 'open',
          target_field: row.messages[0]?.field ?? null, note: null, source: batch.kind,
          import_row_id: row.id, filename: batch.filename, hostname: row.hostname,
          cable_label: row.label, trail: null, epif_request_id: null, device_id: null,
          device_psu_assignment_id: null, connection_id: null, cable_id: null,
          created_by: ACTOR, deferred_at: null, deferred_by: null, resolved_at: null, resolved_by: null,
        })
      }
      if (row.result === 'ready' || row.result === 'warning') {
        if (batch.kind === 'epif') job.device_count += 1
        if (batch.kind === 'cable_matrix') job.connection_count += 1
        row.result = 'committed'
      }
    }
    batch.status = 'committed'
    batch.counts = countsOf(batch.rows)
    resolveSkipItem(job, batch.kind)
  }
  job.updated_at = iso()
  const committed = flags(job)
  return {
    job: committed,
    imports: store.imports.filter((i) => i.job_id === job.id),
    warnings,
    skipped_conflicts,
    open_item_count: committed.unresolved_count,
    items: store.items.filter((i) => i.job_id === job.id),
  } satisfies IntakeCommitResult
}

export function createMockJobIntakeApi(): JobIntakeApi {
  store = empty()
  return {
    async createJob(raw) {
      const dcreq = normalizeDcreq(raw)
      if (!isValidDcreq(dcreq) || !DCREQ_PATTERN.test(dcreq)) {
        throwApi(422, 'dcreq_format', 'Enter a DCREQ like DCREQ0001234 (DCREQ000 + 4 digits).')
      }
      const found = store.jobs.find((j) => j.dcreq === dcreq)
      if (found) {
        const job = flags(found)
        throwApi(
          409,
          'job_exists',
          `${job.dcreq} is already a job (${job.name}, ${job.status}). Attaching more work to that job isn’t available yet.`,
          { existing: existingRef(job) },
        )
      }
      const created = seedMockJob({ dcreq })
      for (const kind of ['epif', 'cable_matrix'] as const) {
        addItem({
          job_id: created.id, dcreq: created.dcreq, item_type: skipType(kind), status: 'open',
          target_field: null, note: null, source: 'manual', import_row_id: null, filename: null,
          hostname: null, cable_label: null, trail: null, epif_request_id: null, device_id: null,
          device_psu_assignment_id: null, connection_id: null, cable_id: null,
          created_by: ACTOR, deferred_at: null, deferred_by: null, resolved_at: null, resolved_by: null,
        })
      }
      return flags(created)
    },
    async getJob(idOrDcreq) {
      return getJobOrThrow(idOrDcreq)
    },
    async listJobs(params: JobListParams = {}) {
      let items = store.jobs.map((j) => flags(j))
      if (params.status) items = items.filter((j) => j.status === params.status)
      if (params.overdue) items = items.filter((j) => j.overdue)
      if (params.recently_closed) items = items.filter((j) => j.recently_closed)
      if (params.q) {
        const q = params.q.trim().toUpperCase()
        items = items.filter((j) => j.dcreq.includes(q) || j.name.toUpperCase().includes(q) || normalizeDcreq(params.q ?? '') === j.dcreq)
      }
      items.sort((a, b) => (params.recently_closed ? (b.closed_at ?? '').localeCompare(a.closed_at ?? '') : b.opened_at.localeCompare(a.opened_at)))
      const total = items.length
      const off = params.offset ?? 0
      const lim = params.limit ?? 50
      return { items: items.slice(off, off + lim), total }
    },
    async closeJob(id, opts = {}) {
      const job = findJob(id)
      if (job.status === 'closed') throwApi(409, 'job_already_closed', 'This job is already closed', { closed_at: job.closed_at })
      const unresolved = flags(job).unresolved_count
      if (unresolved && !opts.acknowledge_open_items) {
        throwApi(
          409,
          'job_has_open_items',
          `This job still has ${unresolved} unresolved item${unresolved === 1 ? '' : 's'}. Close again with acknowledge_open_items=true to close it anyway.`,
          { unresolved_count: unresolved },
        )
      }
      job.status = 'closed'
      job.closed_at = iso()
      job.closed_by = ACTOR
      job.updated_at = job.closed_at
      const closed = flags(job)
      const warning = unresolved > 0
        ? { code: 'job_has_open_items' as const, message: `This job still has ${unresolved} unresolved item${unresolved === 1 ? '' : 's'}.`, unresolved_count: unresolved }
        : null
      return { job: closed, warning }
    },
    async reopenJob(id) {
      const job = findJob(id)
      if (job.status === 'open') throwApi(409, 'job_already_open', 'This job is already open')
      job.status = 'open'
      job.closed_at = null
      job.closed_by = null
      job.updated_at = iso()
      return flags(job)
    },
    async abandonJob(id) {
      const job = findJob(id)
      const committed = store.imports.some((i) => i.job_id === id && i.status === 'committed')
      const resolved = store.items.some((i) => i.job_id === id && (i.status === 'resolved' || i.status === 'dismissed'))
      if (committed || resolved || job.device_count > 0 || job.connection_count > 0) {
        throwApi(409, 'job_not_empty', 'This job already has committed work, so it can’t be deleted. Close it instead.')
      }
      store.imports = store.imports.filter((i) => i.job_id !== id)
      store.items = store.items.filter((i) => i.job_id !== id)
      store.skipped = store.skipped.filter((s) => s.jobId !== id)
      store.jobs = store.jobs.filter((j) => j.id !== id)
    },
    async stageImport(jobId, kind, file) {
      const job = getJobOrThrow(jobId)
      if (!file.name.toLowerCase().endsWith('.csv')) throwApi(422, 'validation', 'Upload a .csv file.')
      if (file.size > JOB_INTAKE_MAX_FILE_BYTES) throwApi(422, 'validation', 'This file is larger than 8 MiB.')
      const text = await file.text()
      const { headers, rows } = parseCsv(text)
      const forbidden = headers.filter((h) => FORBIDDEN.test(h))
      if (forbidden.length) {
        throwApi(
          422,
          'import_forbidden_columns',
          `This file has forbidden columns: ${forbidden.join(', ')}. Remove those columns and upload again. Secrets are never stored.`,
          { headers: forbidden },
        )
      }
      const sha = shaOf(text, file.name)
      const same = store.imports.find((i) => i.job_id === jobId && i.kind === kind && i.sha256 === sha)
      if (same && same.status === 'review') {
        return same
      }
      const parsed: ImportRow[] = rows.map((cells) => {
        const hostname = col(headers, cells, 'hostname', 'host_name', 'name', 'a name')
        const label = col(headers, cells, 'label', 'cable label', 'trail')
        const marked = (col(headers, cells, 'result') ?? '').toLowerCase() as ImportRowResult | ''
        let result: ImportRowResult = marked && ['ready', 'warning', 'held', 'conflict'].includes(marked)
          ? marked
          : 'ready'
        const messages: ImportRow['messages'] = []
        if (hostname?.toUpperCase().startsWith('CONFLICT')) {
          result = 'conflict'
          messages.push({ code: 'hostname_conflict', field: 'hostname', message: `Host name '${hostname}' already exists in that cabinet.` })
        } else if (result === 'warning') {
          messages.push({ code: 'missing_position', field: 'position_u', message: 'No RU.' })
        } else if (result === 'held') {
          messages.push({ code: 'missing_hostname', field: null, message: 'A or Z end could not be resolved.' })
        } else if (result === 'conflict' && !messages.length) {
          messages.push({ code: 'hostname_conflict', field: 'hostname', message: 'This row conflicts with a live record.' })
        }
        return { id: store.nextRow++, row_number: 0, result, messages, hostname, label }
      })
      parsed.forEach((r, i) => { r.row_number = i + 1 })
      const batch: JobImport = {
        id: store.nextImport++,
        job_id: job.id,
        dcreq: job.dcreq,
        kind,
        filename: file.name,
        sha256: sha,
        status: 'review',
        uploaded_at: iso(),
        uploaded_by: ACTOR,
        counts: countsOf(parsed),
        rows: parsed,
      }
      store.imports.push(batch)
      store.skipped = store.skipped.filter((s) => !(s.jobId === jobId && s.kind === kind))
      return batch
    },
    async previewJob(jobId) {
      const job = getJobOrThrow(jobId)
      const latest = (kind: ImportKind) => {
        const all = store.imports.filter((i) => i.job_id === jobId && i.kind === kind)
        return all[all.length - 1] ?? null
      }
      const epif = latest('epif')
      const cable = latest('cable_matrix')
      const skipped = { epif: !epif, cable_matrix: !cable }
      const pending: JobOpenItem[] = []
      for (const batch of [epif, cable]) {
        if (!batch || batch.status === 'committed') continue
        for (const row of batch.rows) {
          if (row.result === 'ready') continue
          pending.push({
            id: 0,
            job_id: job.id,
            dcreq: job.dcreq,
            item_type: (row.messages[0]?.code as OpenItemType) || 'other',
            status: 'open',
            target_field: row.messages[0]?.field ?? null,
            note: null,
            source: batch.kind,
            epif_request_id: null,
            device_id: null,
            device_psu_assignment_id: null,
            connection_id: null,
            cable_id: null,
            import_row_id: row.id,
            filename: batch.filename,
            hostname: row.hostname,
            cable_label: row.label,
            trail: null,
            created_at: iso(),
            created_by: ACTOR,
            deferred_at: null,
            deferred_by: null,
            resolved_at: null,
            resolved_by: null,
          })
        }
      }
      const existing = store.items.filter((i) => i.job_id === jobId && (i.status === 'open' || i.status === 'deferred'))
      for (const item of existing) {
        const kind = item.item_type === 'epif_not_uploaded' ? 'epif' as const
          : item.item_type === 'cable_matrix_not_uploaded' ? 'cable_matrix' as const
          : null
        if (kind && (kind === 'epif' ? epif : cable)) continue // a staged file will resolve this on commit
        pending.push(item)
      }
      return { job, epif, cable_matrix: cable, skipped, pending_items: pending }
    },
    async commitImport(jobId, importId) {
      const job = findJob(jobId)
      const batch = store.imports.find((i) => i.job_id === jobId && i.id === importId && i.status === 'review')
      if (!batch) throwApi(404, 'not_found', 'Import not found')
      return finalizeCommit(job, [batch])
    },
    async commitIntake(jobId) {
      const job = findJob(jobId)
      return finalizeCommit(job, store.imports.filter((i) => i.job_id === jobId && i.status === 'review'))
    },
    async listOpenItems(jobId, status: OpenItemListStatus = 'unresolved') {
      getJobOrThrow(jobId)
      const match = (s: OpenItemStatus) =>
        status === 'all' ? true
        : status === 'unresolved' ? s === 'open' || s === 'deferred'
        : s === status
      const items = store.items.filter((i) => i.job_id === jobId && match(i.status))
      return { items, total: items.length }
    },
    async deferItem(jobId, itemId, note = null) {
      const item = getItem(jobId, itemId)
      item.status = 'deferred'
      item.deferred_at = iso()
      item.deferred_by = ACTOR
      if (note != null) item.note = note
      return item
    },
    async undeferItem(jobId, itemId) {
      const item = getItem(jobId, itemId)
      item.status = 'open'
      item.deferred_at = null
      item.deferred_by = null
      return item
    },
    async dismissItem(jobId, itemId, note) {
      if (!note || !note.trim()) throwApi(422, 'validation', 'A note is required to dismiss an item.')
      const item = getItem(jobId, itemId)
      item.status = 'dismissed'
      item.note = note
      item.resolved_at = iso()
      item.resolved_by = ACTOR
      return item
    },
    async resolveItem(jobId, itemId) {
      const item = getItem(jobId, itemId)
      item.status = 'resolved'
      item.resolved_at = iso()
      item.resolved_by = ACTOR
      return item
    },
    async fillItem(jobId, itemId, value) {
      const trimmed = value.trim()
      if (!trimmed) throwApi(422, 'validation', 'Enter a value to fill this field.')
      const item = getItem(jobId, itemId)
      item.filled_value = trimmed
      item.note = item.target_field ? `${item.target_field}=${trimmed}` : trimmed
      item.status = 'resolved'
      item.resolved_at = iso()
      item.resolved_by = ACTOR
      return item
    },
  }
}
