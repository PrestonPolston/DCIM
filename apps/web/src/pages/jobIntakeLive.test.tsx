import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { JOB_INTAKE_API, type Job, type JobOpenItem } from '../api/jobIntake'
import { setCsrfToken } from '../api/client'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { renderWithProviders } from '../test/render'

type JobCall = { method: string; path: string }

function iso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
}

function overdueAt(openedAt: string) {
  const d = new Date(openedAt)
  d.setUTCDate(d.getUTCDate() + 30)
  return d.toISOString().replace(/\.\d{3}Z$/, 'Z')
}

function installLiveJobsApi() {
  const jobs: Job[] = []
  const items: JobOpenItem[] = []
  let nextJob = 1
  let nextItem = 1
  const jobCalls: JobCall[] = []

  function flags(job: Job): Job {
    const mine = items.filter((i) => i.job_id === job.id)
    const unresolved = mine.filter((i) => i.status === 'open' || i.status === 'deferred')
    return {
      ...job,
      current: job.status === 'open',
      overdue: false,
      overdue_at: overdueAt(job.opened_at),
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
        epif_request_id: null,
        device_id: null,
        device_psu_assignment_id: null,
        connection_id: null,
        cable_id: null,
        import_row_id: null,
        filename: null,
        hostname: null,
        cable_label: null,
        trail: null,
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

  function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    })
  }

  const calls = installMockApi(seedDb())
  const inner = globalThis.fetch as typeof fetch
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    const url = new URL(String(input), 'http://x')
    const path = url.pathname.replace(/^\/api/, '')
    if (path === '/jobs' || path.startsWith('/jobs/')) {
      jobCalls.push({ method, path: path + url.search })
      if (path === '/jobs' && method === 'POST') {
        let body: { dcreq?: string; name?: string } = {}
        try { body = JSON.parse(String(init?.body ?? '{}')) as { dcreq?: string; name?: string } } catch { /* ignore */ }
        const dcreq = (body.dcreq ?? '').trim().replace(/\s+/g, '').toUpperCase()
        const existing = jobs.find((j) => j.dcreq === dcreq)
        if (existing) {
          return json({ detail: { code: 'job_exists', message: 'Job exists', existing: { id: existing.id, dcreq: existing.dcreq, name: existing.name, status: existing.status, is_job: true, deleted: false } } }, 409)
        }
        const now = iso()
        const job: Job = {
          id: nextJob++,
          name: body.name ?? dcreq,
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
          connection_count: 0,
        }
        // fix primary_dcreq_id typo - don't reference job.id before assignment complete
        job.primary_dcreq_id = job.id
        jobs.push(job)
        addNotUploaded(job)
        return json(flags(job), 201)
      }
      if (path === '/jobs' && method === 'GET') {
        const listed = jobs.map(flags)
        return json(listed, 200, { 'X-Total-Count': String(listed.length) })
      }
      const closeM = path.match(/^\/jobs\/([^/]+)\/close$/)
      if (closeM && method === 'POST') {
        const job = findJob(closeM[1])
        if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
        const unresolved = flags(job).unresolved_count
        let body: { acknowledge_open_items?: boolean } = {}
        try { body = JSON.parse(String(init?.body ?? '{}')) as { acknowledge_open_items?: boolean } } catch { /* ignore */ }
        if (unresolved && !body.acknowledge_open_items) {
          return json({
            detail: {
              code: 'job_has_open_items',
              message: 'Close again with acknowledge_open_items=true to close it anyway.',
              unresolved_count: unresolved,
            },
          }, 409)
        }
        job.status = 'closed'
        job.closed_at = iso()
        return json({ job: flags(job), warning: unresolved ? { code: 'job_has_open_items', unresolved_count: unresolved, message: 'This job still has unresolved items.' } : null })
      }
      const reopenM = path.match(/^\/jobs\/([^/]+)\/reopen$/)
      if (reopenM && method === 'POST') {
        const job = findJob(reopenM[1])
        if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
        job.status = 'open'
        job.closed_at = null
        return json({ job: flags(job) })
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
      const writeM = path.match(/^\/jobs\/([^/]+)\/open-items\/\d+\/(defer|undefer|dismiss|resolve|fill)$/)
      if (writeM) return json({ detail: 'Not Found' }, 404)
      if (/^\/jobs\/[^/]+\/imports/.test(path) || /\/preview$/.test(path) || /\/commit$/.test(path)) {
        return json({ detail: 'Not Found' }, 404)
      }
      const one = path.match(/^\/jobs\/([^/]+)$/)
      if (one && method === 'GET') {
        const job = findJob(one[1])
        if (!job) return json({ detail: { code: 'job_not_found', message: 'Job not found' } }, 404)
        return json(flags(job))
      }
      if (one && method === 'DELETE') {
        return json({ detail: 'Method Not Allowed' }, 405)
      }
      return json({ detail: 'Not Found' }, 404)
    }
    return inner(input, init)
  })

  return { jobs, items, jobCalls, calls, seedJob(dcreq: string, name = dcreq) {
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
      connection_count: 0,
    }
    job.primary_dcreq_id = job.id
    jobs.push(job)
    addNotUploaded(job)
    return flags(job)
  } }
}

describe('job intake live flag (mocked fetch)', () => {
  beforeEach(() => {
    resetAuth({ role: 'admin' })
    setCsrfToken('csrf-1')
    JOB_INTAKE_API.live = true
    JOB_INTAKE_API.openItemWrites = false
    JOB_INTAKE_API.imports = false
  })

  afterEach(() => {
    JOB_INTAKE_API.live = false
    JOB_INTAKE_API.openItemWrites = false
    JOB_INTAKE_API.imports = false
    vi.unstubAllGlobals()
  })

  it('disables queue actions and shows the pending-API note', async () => {
    const live = installLiveJobsApi()
    live.seedJob('DCREQ0001234', 'Leaf refresh')
    renderWithProviders(<App />, '/jobs/DCREQ0001234')
    await screen.findByRole('heading', { name: 'DCREQ0001234' })
    expect(screen.getByRole('note')).toHaveTextContent('Complete, Fill, Hold and Dismiss arrive with the next API update.')
    await screen.findByRole('region', { name: 'ePIF not uploaded' })
    const actions = ['Complete', 'Resolve with note', 'Hold', 'Dismiss']
    for (const name of actions) {
      const buttons = screen.getAllByRole('button', { name })
      expect(buttons.length).toBeGreaterThan(0)
      for (const btn of buttons) expect(btn).toBeDisabled()
    }
    expect(live.jobCalls.some((c) => /open-items\/\d+\//.test(c.path))).toBe(false)
  })

  it('live Skip does not call the server, and the no-import path finishes on the job page', async () => {
    const live = installLiveJobsApi()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/new')
    await screen.findByRole('heading', { name: 'New job' })
    await user.type(screen.getByLabelText('DCREQ'), 'DCREQ0001234')
    await user.click(screen.getByRole('button', { name: 'Next: ePIF' }))
    expect(await screen.findByRole('heading', { name: 'New job · DCREQ0001234' })).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(/CSV import isn't available yet/)
    await user.click(screen.getByRole('button', { name: 'Skip ePIF' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/ePIF not uploaded item created with this job will stay open/)
    expect(live.jobCalls.filter((c) => c.path.includes('/imports') || c.path.includes('/skip') || c.path.includes('/preview'))).toEqual([])
    await user.click(screen.getByRole('button', { name: 'Next: Cable matrix' }))
    expect(screen.getByRole('note')).toHaveTextContent(/CSV import isn't available yet/)
    await user.click(screen.getByRole('button', { name: 'Finish' }))
    expect(await screen.findByRole('heading', { name: 'DCREQ0001234' })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Job created' })).toHaveTextContent(
      'This job was created, and the ePIF and cable-matrix items are waiting in its fill-later queue.',
    )
    expect(screen.queryByText(/^Not Found$/)).toBeNull()
    expect(await screen.findByRole('region', { name: 'ePIF not uploaded' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Cable matrix not uploaded' })).toBeInTheDocument()
    expect(live.jobCalls.filter((c) => c.path.includes('/imports') || c.path.includes('/preview') || c.path.includes('/commit'))).toEqual([])
  })

  it('live Cancel after create says the job still exists and links to it, without deleting', async () => {
    const live = installLiveJobsApi()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/new')
    await screen.findByRole('heading', { name: 'New job' })
    await user.type(screen.getByLabelText('DCREQ'), 'DCREQ0005678')
    await user.click(screen.getByRole('button', { name: 'Next: ePIF' }))
    await screen.findByRole('heading', { name: 'New job · DCREQ0005678' })
    await user.click(screen.getByRole('button', { name: 'Cancel intake' }))
    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent('DCREQ0005678 still exists as a job')
    const link = within(banner).getByRole('link', { name: 'Open DCREQ0005678' })
    expect(link).toHaveAttribute('href', '/jobs/DCREQ0005678')
    expect(live.jobCalls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(link)
    expect(await screen.findByRole('heading', { name: 'DCREQ0005678' })).toBeInTheDocument()
    expect(screen.queryByText(/^Not Found$/)).toBeNull()
  })
})
