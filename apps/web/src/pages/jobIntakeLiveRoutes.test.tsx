import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { JOB_INTAKE_API, jobIntakeApi, type Job, type JobOpenItem, type JobImport } from '../api/jobIntake'
import { ApiError } from '../api/client'
import { friendlyMessage, errorDetail } from '../api/errors'
import { setCsrfToken } from '../api/client'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { renderWithProviders } from '../test/render'

function iso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function installSlice2JobsApi() {
  const jobs: Job[] = []
  const items: JobOpenItem[] = []
  const imports: JobImport[] = []
  let nextJob = 1
  let nextItem = 1
  let nextImport = 1
  const jobCalls: { method: string; path: string; body?: string }[] = []

  function flags(job: Job): Job {
    const mine = items.filter((i) => i.job_id === job.id)
    const unresolved = mine.filter((i) => i.status === 'open' || i.status === 'deferred')
    return {
      ...job,
      current: job.status === 'open',
      overdue: false,
      days_open: 0,
      recently_closed: job.status === 'closed',
      days_since_closed: job.status === 'closed' ? 0 : null,
      unresolved_count: unresolved.length,
      deferred_count: mine.filter((i) => i.status === 'deferred').length,
      unresolved_by_type: unresolved.reduce<Record<string, number>>((acc, i) => {
        acc[i.item_type] = (acc[i.item_type] ?? 0) + 1
        return acc
      }, {}),
    }
  }

  function addNotUploaded(job: Job) {
    for (const type of ['epif_not_uploaded', 'cable_matrix_not_uploaded'] as const) {
      items.push({
        id: nextItem++,
        job_id: job.id,
        dcreq: job.dcreq,
        item_type: type,
        status: 'open',
        target_field: null,
        note: null,
        source: 'manual',
        device_id: null,
        connection_id: null,
        cable_id: null,
        import_row_id: null,
        filename: null,
        hostname: null,
        cable_label: null,
        created_at: job.opened_at,
        created_by: 'pat@example.com',
        deferred_at: null,
        deferred_by: null,
        resolved_at: null,
        resolved_by: null,
      })
    }
  }

  function findJob(key: string): Job | undefined {
    const decoded = decodeURIComponent(key)
    if (/^\d+$/.test(decoded)) return jobs.find((j) => j.id === Number(decoded))
    return jobs.find((j) => j.dcreq.toLowerCase() === decoded.toLowerCase())
  }

  function seedJob(dcreq: string, name = dcreq) {
    const now = iso()
    const job: Job = {
      id: nextJob++,
      name,
      dcreq,
      primary_dcreq_id: 0,
      status: 'open',
      opened_at: now,
      closed_at: null,
      closed_by: null,
      created_at: now,
      updated_at: now,
      created_by: 'pat@example.com',
      current: true,
      overdue: false,
      days_open: 0,
      recently_closed: false,
      days_since_closed: null,
      unresolved_count: 2,
      deferred_count: 0,
      device_count: 0,
    }
    job.primary_dcreq_id = job.id
    jobs.push(job)
    addNotUploaded(job)
    return flags(job)
  }

  function addFieldItem(job: Job, hostname: string) {
    const item: JobOpenItem = {
      id: nextItem++,
      job_id: job.id,
      dcreq: job.dcreq,
      item_type: 'missing_position',
      status: 'open',
      target_field: 'position_u',
      note: null,
      source: 'epif',
      device_id: null,
      connection_id: null,
      cable_id: null,
      import_row_id: 1,
      filename: 'epif.csv',
      hostname,
      cable_label: null,
      created_at: iso(),
      created_by: 'pat@example.com',
      deferred_at: null,
      deferred_by: null,
      resolved_at: null,
      resolved_by: null,
    }
    items.push(item)
    return item
  }

  const calls = installMockApi(seedDb())
  const inner = globalThis.fetch as typeof fetch
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    const url = new URL(String(input), 'http://x')
    const path = url.pathname.replace(/^\/api/, '')
    if (!(path === '/jobs' || path.startsWith('/jobs/'))) return inner(input, init)
    const rawBody = typeof init?.body === 'string' ? init.body : undefined
    jobCalls.push({ method, path: path + url.search, body: rawBody })

    if (path === '/jobs' && method === 'POST') {
      let body: { dcreq?: string; name?: string } = {}
      try { body = JSON.parse(rawBody ?? '{}') as { dcreq?: string; name?: string } } catch { /* ignore */ }
      const dcreq = (body.dcreq ?? '').trim().replace(/\s+/g, '').toUpperCase()
      const existing = jobs.find((j) => j.dcreq === dcreq)
      if (existing) {
        return json({ detail: { code: 'job_exists', message: 'Job exists', existing: { id: existing.id, dcreq: existing.dcreq, name: existing.name, status: existing.status, is_job: true, deleted: false } } }, 409)
      }
      return json(seedJob(dcreq, body.name ?? dcreq), 201)
    }
    if (path === '/jobs' && method === 'GET') {
      const listed = jobs.map(flags)
      return json(listed, 200, { 'X-Total-Count': String(listed.length) })
    }

    const uploadM = path.match(/^\/jobs\/([^/]+)\/imports$/)
    if (uploadM && method === 'POST') {
      const job = findJob(uploadM[1])
      if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
      const kind = url.searchParams.get('kind') ?? 'epif'
      const filename = url.searchParams.get('filename') ?? 'upload.csv'
      if (kind === 'cable_matrix') {
        return json({ detail: { code: 'import_kind_not_available', message: "Cable matrix import isn't available yet" } }, 422)
      }
      const text = rawBody ?? ''
      if (/ilo password|secret/i.test(text.split('\n')[0] ?? '')) {
        return json({ detail: { code: 'import_forbidden_columns', message: 'Forbidden columns', headers: ['ilo password'] } }, 422)
      }
      const existing = imports.find((i) => i.job_id === job.id && i.filename === filename && i.kind === 'epif')
      if (existing) {
        return json({ ...existing, reupload: existing.status === 'committed' ? 'committed' : 'review' }, 200)
      }
      const staged: JobImport = {
        id: nextImport++,
        job_id: job.id,
        dcreq: job.dcreq,
        kind: 'epif',
        filename,
        sha256: 'abc',
        status: 'review',
        uploaded_at: iso(),
        uploaded_by: 'pat@example.com',
        counts: { total: 3, ready: 1, warning: 1, held: 0, conflict: 1, committed: 0, skipped: 0 },
        reupload: null,
        rows: [
          { id: 1, row_number: 1, result: 'ready', messages: [], hostname: 'web01', label: null },
          { id: 2, row_number: 2, result: 'warning', messages: [{ code: 'missing_position', field: 'position_u', message: 'No RU.', level: 'warning', item_type: 'missing_position', target_field: 'position_u' }], hostname: 'nopos', label: null },
          { id: 3, row_number: 3, result: 'conflict', messages: [{ code: 'hostname_conflict', field: 'hostname', message: 'Hostname already used.', level: 'conflict', item_type: 'other', target_field: 'hostname' }], hostname: 'web01', label: null },
        ],
      }
      imports.push(staged)
      return json(staged, 201)
    }
    if (uploadM && method === 'GET') {
      const job = findJob(uploadM[1])
      if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
      const status = url.searchParams.get('status')
      const listed = imports.filter((i) => i.job_id === job.id && (!status || i.status === status))
      return json(listed.map((imp) => { const { rows, ...rest } = imp; void rows; return rest }), 200, { 'X-Total-Count': String(listed.length) })
    }

    const oneImport = path.match(/^\/jobs\/([^/]+)\/imports\/(\d+)$/)
    if (oneImport && method === 'GET') {
      const job = findJob(oneImport[1])
      const imp = imports.find((i) => i.id === Number(oneImport[2]) && i.job_id === job?.id)
      if (!imp) return json({ detail: { code: 'import_not_found', message: 'Import not found' } }, 404)
      return json(imp)
    }
    const abandon = path.match(/^\/jobs\/([^/]+)\/imports\/(\d+)\/abandon$/)
    if (abandon && method === 'POST') {
      const imp = imports.find((i) => i.id === Number(abandon[2]))
      if (!imp || imp.status !== 'review') return json({ detail: { code: 'import_not_in_review', message: "This import isn't in review" } }, 409)
      imp.status = 'abandoned'
      return json(imp)
    }
    const commitOne = path.match(/^\/jobs\/([^/]+)\/imports\/(\d+)\/commit$/)
    const commitAll = path.match(/^\/jobs\/([^/]+)\/commit$/)
    if ((commitOne || commitAll) && method === 'POST') {
      const key = (commitOne ?? commitAll)![1]
      const job = findJob(key)
      if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
      const batches = commitOne
        ? imports.filter((i) => i.id === Number(commitOne[2]) && i.job_id === job.id)
        : imports.filter((i) => i.job_id === job.id && i.status === 'review')
      if (batches.length === 0) return json({ detail: { code: 'no_review_imports', message: 'There are no imports in review on this job' } }, 409)
      if (batches.some((b) => b.status !== 'review')) return json({ detail: { code: 'import_not_in_review', message: "This import isn't in review" } }, 409)
      for (const b of batches) b.status = 'committed'
      const epif = items.find((i) => i.job_id === job.id && i.item_type === 'epif_not_uploaded' && i.status === 'open')
      if (epif) {
        epif.status = 'resolved'
        epif.resolved_at = iso()
        epif.resolved_by = 'pat@example.com'
      }
      const pos = addFieldItem(job, 'nopos')
      const other = items.find((i) => i.id === pos.id)
      void other
      job.device_count = 1
      const view = flags(job)
      return json({
        job: view,
        imports: batches,
        committed: [{ import_id: batches[0].id, kind: 'epif', row_number: 1, hostname: 'web01', reasons: [] }],
        held: [],
        skipped: [{
          import_id: batches[0].id,
          kind: 'epif',
          row_number: 3,
          hostname: 'web01',
          reasons: [{ code: 'hostname_conflict', field: 'hostname', message: 'Hostname already used.', level: 'conflict', item_type: 'other' }],
        }],
        warnings: [
          { code: 'missing_position', message: 'No RU.', field: 'position_u', item_type: 'missing_position', target_field: 'position_u', import_id: batches[0].id, row_number: 2, hostname: 'nopos' },
          { code: 'pdu_missing', message: 'No PDU.', field: 'psu_1', item_type: 'pdu_missing', target_field: 'psu_1', import_id: batches[0].id, row_number: 4, hostname: 'web11' },
        ],
        open_items_created: [pos.id],
        open_item_count: view.unresolved_count,
        resolved_item_ids: epif ? [epif.id] : [],
      })
    }

    const writeM = path.match(/^\/jobs\/([^/]+)\/open-items\/(\d+)\/(defer|undefer|dismiss|resolve|fill)$/)
    if (writeM && method === 'POST') {
      const job = findJob(writeM[1])
      const item = items.find((i) => i.id === Number(writeM[2]) && i.job_id === job?.id)
      if (!job || !item) return json({ detail: { code: 'open_item_not_found', message: 'Open item not found' } }, 404)
      const action = writeM[3]
      let body: { note?: string } = {}
      try { body = JSON.parse(rawBody ?? '{}') as { note?: string } } catch { /* ignore */ }
      if (item.status === 'resolved' || item.status === 'dismissed') {
        return json({ detail: { code: 'open_item_closed', message: `This item is already ${item.status}`, status: item.status } }, 409)
      }
      if (action === 'dismiss' && !body.note?.trim()) {
        return json({ detail: { code: 'note_required', message: 'Say why this item is dismissed', field: 'note' } }, 422)
      }
      if (action === 'defer') {
        if (item.status !== 'open') return json({ detail: { code: 'open_item_state', message: 'That action is not valid' } }, 409)
        item.status = 'deferred'
        item.deferred_at = iso()
        item.deferred_by = 'pat@example.com'
        if (body.note) item.note = `Deferred: ${body.note}`
      } else if (action === 'undefer') {
        if (item.status !== 'deferred') return json({ detail: { code: 'open_item_state', message: 'That action is not valid' } }, 409)
        item.status = 'open'
        item.deferred_at = null
        item.deferred_by = null
      } else if (action === 'dismiss') {
        item.status = 'dismissed'
        item.note = `Dismissed: ${body.note}`
        item.resolved_at = iso()
        item.resolved_by = 'pat@example.com'
        item.deferred_at = null
        item.deferred_by = null
      } else if (action === 'resolve') {
        item.status = 'resolved'
        if (body.note) item.note = `Resolved: ${body.note}`
        item.resolved_at = iso()
        item.resolved_by = 'pat@example.com'
        item.deferred_at = null
        item.deferred_by = null
      } else {
        return json({ detail: 'Not Found' }, 404)
      }
      return json({ item, job: flags(job) })
    }

    const itemsM = path.match(/^\/jobs\/([^/]+)\/open-items$/)
    if (itemsM && method === 'GET') {
      const job = findJob(itemsM[1])
      if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
      const status = url.searchParams.get('status') ?? 'unresolved'
      const match = (s: string) =>
        status === 'all' ? true
        : status === 'unresolved' ? s === 'open' || s === 'deferred'
        : s === status
      const listed = items.filter((i) => i.job_id === job.id && match(i.status))
      return json(listed, 200, { 'X-Total-Count': String(listed.length) })
    }

    const one = path.match(/^\/jobs\/([^/]+)$/)
    if (one && method === 'GET') {
      const job = findJob(one[1])
      if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
      return json(flags(job))
    }
    return json({ detail: 'Not Found' }, 404)
  })

  return { jobs, items, imports, jobCalls, calls, seedJob, addFieldItem, flags }
}

const csv = (name: string, text: string) => new File([text], name, { type: 'text/csv' })
const EPIF = 'ID,Action,Name,Manufacturer,Model,Row,Rack,RU,S/N\n10001,Install,web01,Acme,1U,Row 1,R01,1,S1\n10002,Install,nopos,Acme,1U,Row 1,R01,,S3\n10003,Install,web01,Acme,1U,Row 1,R01,2,S2\n'

describe('job intake live slice 2 routes (mocked fetch)', () => {
  beforeEach(() => {
    resetAuth({ role: 'admin' })
    setCsrfToken('csrf-1')
    JOB_INTAKE_API.live = true
    JOB_INTAKE_API.openItemWrites = true
    JOB_INTAKE_API.imports = true
    JOB_INTAKE_API.cableImports = false
  })

  afterEach(() => {
    JOB_INTAKE_API.live = false
    JOB_INTAKE_API.openItemWrites = false
    JOB_INTAKE_API.imports = false
    JOB_INTAKE_API.cableImports = false
    vi.unstubAllGlobals()
  })

  it('stages a CSV as text/csv, returns a preview, and treats a re-upload as 200', async () => {
    const live = installSlice2JobsApi()
    const job = live.seedJob('DCREQ0001234')
    const first = await jobIntakeApi().stageImport(job.id, 'epif', csv('epif.csv', EPIF))
    expect(first.status).toBe('review')
    expect(first.counts).toMatchObject({ total: 3, ready: 1, warning: 1, conflict: 1 })
    expect(first.rows?.some((r) => r.result === 'conflict' && r.hostname === 'web01')).toBe(true)
    const post = live.jobCalls.filter((c) => c.method === 'POST' && c.path.startsWith(`/jobs/${job.id}/imports`))
    expect(post[0].path).toContain('kind=epif')
    expect(post[0].path).toContain('filename=epif.csv')
    expect(post[0].body).toContain('web01')
    const again = await jobIntakeApi().stageImport(job.id, 'epif', csv('epif.csv', EPIF))
    expect(again.reupload).toBe('review')
    const preview = await jobIntakeApi().previewJob(job.id)
    expect(preview.epif?.id).toBe(first.id)
    expect(preview.skipped.cable_matrix).toBe(true)
    expect(preview.pending_items.some((i) => i.item_type === 'missing_position')).toBe(true)
  })

  it('maps commit skipped rows and unwraps open-item writes with updated job counts', async () => {
    const live = installSlice2JobsApi()
    const job = live.seedJob('DCREQ0001234')
    await jobIntakeApi().stageImport(job.id, 'epif', csv('epif.csv', EPIF))
    const committed = await jobIntakeApi().commitIntake(job.id)
    expect(committed.job.device_count).toBe(1)
    expect(committed.skipped_conflicts).toEqual([
      expect.objectContaining({ row_number: 3, hostname: 'web01', messages: [expect.objectContaining({ code: 'hostname_conflict' })] }),
    ])
    const pos = committed.items.find((i) => i.item_type === 'missing_position')!
    const before = committed.job.unresolved_count
    const filled = await jobIntakeApi().fillItem(job.id, pos.id, '42')
    expect(live.jobCalls.some((c) => c.method === 'POST' && c.path.endsWith(`/open-items/${pos.id}/resolve`) && c.body?.includes('42'))).toBe(true)
    expect(filled.item.status).toBe('resolved')
    expect(filled.item.note).toBe('Resolved: 42')
    expect(filled.job.unresolved_count).toBe(before - 1)

    const cable = (await jobIntakeApi().listOpenItems(job.id, 'unresolved')).items.find((i) => i.item_type === 'cable_matrix_not_uploaded')!
    const held = await jobIntakeApi().deferItem(job.id, cable.id, 'later')
    expect(held.item.status).toBe('deferred')
    expect(held.job.deferred_count).toBe(1)
    const dismissed = await jobIntakeApi().dismissItem(job.id, cable.id, 'not needed')
    expect(dismissed.item.status).toBe('dismissed')
    expect(dismissed.job.deferred_count).toBe(0)
  })

  it('returns friendly text for cable-matrix, forbidden columns, note_required and open_item_closed', async () => {
    const live = installSlice2JobsApi()
    const job = live.seedJob('DCREQ0001234')
    await expect(jobIntakeApi().stageImport(job.id, 'cable_matrix', csv('cables.csv', 'Name\nx\n'))).rejects.toMatchObject({ status: 422, code: 'import_kind_not_available' })
    try {
      await jobIntakeApi().stageImport(job.id, 'epif', csv('secrets.csv', 'Name,ilo password\nbox,hunter2\n'))
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError)
      const err = e as ApiError
      expect(friendlyMessage(errorDetail(err.detail)!, 422)).toMatch(/ilo password/i)
      expect(err.message).not.toContain('hunter2')
    }
    const item = live.addFieldItem(job, 'leaf-04')
    await expect(jobIntakeApi().dismissItem(job.id, item.id, '   ')).rejects.toMatchObject({ status: 422, code: 'note_required' })
    await jobIntakeApi().resolveItem(job.id, item.id)
    try {
      await jobIntakeApi().resolveItem(job.id, item.id)
      throw new Error('expected 409')
    } catch (e) {
      const err = e as ApiError
      expect(err.status).toBe(409)
      expect(err.code).toBe('open_item_closed')
      expect(friendlyMessage(errorDetail(err.detail)!, 409)).toBe('This item is already completed.')
    }
  })

  it('uploads ePIF, skips cable matrix, and lists skipped conflict rows after commit', async () => {
    installSlice2JobsApi()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/new')
    await screen.findByRole('heading', { name: 'New job' })
    await user.type(screen.getByLabelText('DCREQ'), 'DCREQ0001234')
    await user.click(screen.getByRole('button', { name: 'Next: ePIF' }))
    await screen.findByRole('heading', { name: 'New job · DCREQ0001234' })
    await user.upload(screen.getByLabelText('Space & Power (ePIF) CSV'), csv('epif.csv', EPIF))
    expect(await screen.findByRole('status')).toHaveTextContent('epif.csv: 3 rows')
    await user.click(screen.getByRole('button', { name: 'Next: Cable matrix' }))
    expect(screen.getByRole('note')).toHaveTextContent(/Cable matrix import isn't available yet/)
    await user.click(screen.getByRole('button', { name: 'Skip cable matrix' }))
    await user.click(screen.getByRole('button', { name: 'Next: Preview' }))
    expect(await screen.findByRole('heading', { name: /Preview/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Commit job/ }))
    const result = await screen.findByRole('region', { name: 'Import result' })
    const skipped = within(result).getByRole('table', { name: 'Skipped conflict rows' })
    expect(skipped).toHaveTextContent('web01')
    expect(skipped).toHaveTextContent('Hostname already used.')
    expect(result.textContent).toMatch(/1 device ·/)
    expect(result.textContent).not.toMatch(/1 devices/)
    expect(result).toHaveTextContent('Missing PDU')
    expect(result).toHaveTextContent('Missing position')
    expect(result.textContent).not.toMatch(/\(pdu_missing\)/)
    expect(result.textContent).not.toMatch(/\(missing_position\)/)
  })

  it('Resolve with note posts resolve, explains that the field is not written, and links the device', async () => {
    const live = installSlice2JobsApi()
    const job = live.seedJob('DCREQ0001234', 'Leaf refresh')
    const item = live.addFieldItem(job, 'nopos')
    item.device_id = 42
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/DCREQ0001234')
    await screen.findByRole('heading', { name: 'Fill-later queue' })
    const positions = await screen.findByRole('region', { name: 'Missing position' })
    expect(within(positions).getByRole('note')).toHaveTextContent("Complete marks this resolved. It doesn't write position (U).")
    expect(screen.queryByRole('button', { name: 'Fill' })).toBeNull()
    const before = screen.getByTestId('job-queue-summary').textContent ?? ''
    const start = Number(/(\d+) in the fill-later queue/.exec(before)?.[1])
    await user.click(within(positions).getByRole('button', { name: 'Resolve with note' }))
    const honesty = screen.getByRole('note', { name: 'Resolve with note' })
    expect(honesty).toHaveTextContent('This marks the item resolved and keeps your note.')
    expect(honesty).toHaveTextContent("It doesn't change nopos")
    expect(honesty).toHaveTextContent('set position (U) on the device page')
    expect(within(honesty).getByRole('link', { name: 'the device page' })).toHaveAttribute('href', '/devices?q=nopos')
    expect(screen.getByLabelText('Note')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Value for/)).toBeNull()
    await user.type(screen.getByLabelText('Note'), '42')
    await user.click(screen.getByRole('button', { name: 'Save and resolve' }))
    await waitFor(() => {
      expect(screen.getByTestId('job-queue-summary')).toHaveTextContent(`${start - 1} in the fill-later queue`)
    })
    expect(live.jobCalls.some((c) => c.path.endsWith('/resolve') && c.body?.includes('42'))).toBe(true)
    await user.click(screen.getByRole('tab', { name: /^Resolved$/ }))
    expect(await screen.findByRole('region', { name: 'Missing position' })).toHaveTextContent('Resolved: 42')
  })
})
