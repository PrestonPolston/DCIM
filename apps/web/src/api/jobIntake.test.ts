import { beforeEach, describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { friendlyMessage, errorDetail } from './errors'
import {
  DCREQ_PATTERN,
  JOB_INTAKE_API,
  JOB_OVERDUE_DAYS,
  daysBetween,
  duplicateExisting,
  isDuplicateDcreq,
  isJobOverdue,
  isValidDcreq,
  jobHref,
  jobIntakeApi,
  normalizeDcreq,
  resetJobIntakeMock,
} from './jobIntake'
import { seedMockJob } from './jobIntake.mock'

const api = () => jobIntakeApi()
const csv = (body: string, name = 'epif.csv') => new File([body], name, { type: 'text/csv' })
const agoZ = (days: number, extraMs = 0) =>
  new Date(Date.now() - days * 86_400_000 - extraMs).toISOString().replace(/\.\d{3}Z$/, 'Z')

beforeEach(() => {
  JOB_INTAKE_API.live = false
  resetJobIntakeMock()
})

describe('normalizeDcreq', () => {
  it('rebuilds a paste of the full id, 000XXXX, or the last 4 digits', () => {
    expect(normalizeDcreq('  dcreq0001234  ')).toBe('DCREQ0001234')
    expect(normalizeDcreq('DCREQ 000 1234')).toBe('DCREQ0001234')
    expect(normalizeDcreq('0001234')).toBe('DCREQ0001234')
    expect(normalizeDcreq('1234')).toBe('DCREQ0001234')
    expect(isValidDcreq('1234')).toBe(true)
    expect(isValidDcreq('DCREQ0001234')).toBe(true)
    expect(DCREQ_PATTERN.test('DCREQ0001234')).toBe(true)
  })

  it('rejects values that are not DCREQ000 + 4 digits', () => {
    expect(isValidDcreq('')).toBe(false)
    expect(isValidDcreq('DCREQ')).toBe(false)
    expect(isValidDcreq('DCREQ1234')).toBe(false)
    expect(isValidDcreq('DCREQ00012')).toBe(false)
    expect(isValidDcreq('DCREQ00012345')).toBe(false)
    expect(isValidDcreq('CHG0001234')).toBe(false)
    expect(isValidDcreq('1')).toBe(false)
  })
})

describe('createJob', () => {
  it('creates an open job from a valid DCREQ and starts the 30-day clock', async () => {
    const job = await api().createJob('1234')
    expect(job.dcreq).toBe('DCREQ0001234')
    expect(job.name).toBe('DCREQ0001234')
    expect(job.status).toBe('open')
    expect(job.current).toBe(true)
    expect(job.overdue).toBe(false)
    expect(job.opened_at).toMatch(/Z$/)
    expect(job.unresolved_count).toBe(0)
    expect(jobHref(job)).toBe('/jobs/DCREQ0001234')
  })

  it('returns 422 dcreq_format and creates nothing when the DCREQ is invalid', async () => {
    await expect(api().createJob('nope')).rejects.toMatchObject({ status: 422, code: 'dcreq_format' })
    expect((await api().listJobs()).total).toBe(0)
  })

  it('hard-stops a duplicate DCREQ with 409 duplicate_dcreq and the existing job', async () => {
    await api().createJob('DCREQ0001234')
    const first = await api().getJob('DCREQ0001234')
    let err: unknown
    try {
      await api().createJob('1234')
    } catch (e) {
      err = e
    }
    expect(isDuplicateDcreq(err)).toBe(true)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).code).toBe('duplicate_dcreq')
    expect(duplicateExisting(err)).toEqual({
      id: first.id, dcreq: 'DCREQ0001234', name: 'DCREQ0001234', status: 'open',
    })
    const d = errorDetail((err as ApiError).detail)!
    expect(friendlyMessage(d, 409)).toBe(
      'DCREQ0001234 is already a job (DCREQ0001234, open). Attaching more work to that job isn’t available yet.',
    )
    expect((await api().listJobs()).total).toBe(1)
  })
})

describe('overdue flag', () => {
  it('flags a job only when it has been open for more than 30 days from opened_at', () => {
    const now = Date.parse('2026-11-12T13:00:00Z')
    expect(isJobOverdue({ status: 'open', opened_at: '2026-10-13T12:59:59Z' }, now)).toBe(true)
    expect(isJobOverdue({ status: 'open', opened_at: '2026-10-13T13:00:00Z' }, now)).toBe(false)
    expect(isJobOverdue({ status: 'open', opened_at: '2026-10-14T13:00:00Z' }, now)).toBe(false)
    expect(isJobOverdue({ status: 'closed', opened_at: '2026-09-01T13:00:00Z' }, now)).toBe(false)
    expect(daysBetween('2026-11-07T13:00:00Z', now)).toBe(5)
    expect(JOB_OVERDUE_DAYS).toBe(30)
  })

  it('lists overdue jobs and does not reset the clock on reopen', async () => {
    seedMockJob({ dcreq: 'DCREQ0002001', name: 'Old leaf', opened_at: agoZ(40) })
    const listed = await api().listJobs({ overdue: true })
    expect(listed.total).toBe(1)
    expect(listed.items[0].overdue).toBe(true)
    expect(listed.items[0].days_open).toBeGreaterThanOrEqual(40)
    await api().closeJob(listed.items[0].id)
    const reopened = await api().reopenJob(listed.items[0].id)
    expect(reopened.status).toBe('open')
    expect(reopened.closed_at).toBeNull()
    expect(reopened.opened_at).toBe(listed.items[0].opened_at)
    expect(reopened.overdue).toBe(true)
  })
})

describe('close with open items', () => {
  it('closes the job and returns a job_has_open_items warning when items remain', async () => {
    const job = await api().createJob('DCREQ0003001')
    await api().skipFile(job.id, 'cable_matrix')
    await api().commitIntake(job.id)
    const result = await api().closeJob(job.id)
    expect(result.job.status).toBe('closed')
    expect(result.job.current).toBe(false)
    expect(result.job.overdue).toBe(false)
    expect(result.job.closed_at).toMatch(/Z$/)
    expect(result.warning).toEqual({
      code: 'job_has_open_items',
      unresolved_count: 1,
      message: 'This job still has 1 unresolved item.',
    })
  })

  it('closes with a null warning when the queue is empty', async () => {
    const job = await api().createJob('DCREQ0003002')
    const result = await api().closeJob(job.id)
    expect(result.job.status).toBe('closed')
    expect(result.warning).toBeNull()
  })
})

describe('imports and commit', () => {
  it('rejects secret headers with 422 import_forbidden_columns and stages nothing', async () => {
    const job = await api().createJob('DCREQ0004001')
    const file = csv('hostname,iLO Password\nleaf-01,hunter2\n')
    let err: unknown
    try {
      await api().stageImport(job.id, 'epif', file)
    } catch (e) {
      err = e
    }
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).code).toBe('import_forbidden_columns')
    const d = errorDetail((err as ApiError).detail)!
    expect(d.headers).toEqual(['iLO Password'])
    expect(friendlyMessage(d, 422)).toContain('iLO Password')
    expect(friendlyMessage(d, 422)).not.toContain('hunter2')
    const preview = await api().previewJob(job.id)
    expect(preview.epif).toBeNull()
  })

  it('commits ready rows, warns on missing data, lists skipped conflict rows, and queues fill-later items', async () => {
    const job = await api().createJob('DCREQ0004002')
    const file = csv(
      'hostname,result\n'
      + 'leaf-01,ready\n'
      + 'leaf-04,warning\n'
      + 'CONFLICT-sw,ready\n',
    )
    const staged = await api().stageImport(job.id, 'epif', file)
    expect(staged.counts).toEqual({ total: 3, ready: 1, warning: 1, held: 0, conflict: 1 })
    await api().skipFile(job.id, 'cable_matrix')
    const preview = await api().previewJob(job.id)
    expect(preview.skipped.cable_matrix).toBe(true)
    expect(preview.pending_items.some((i) => i.item_type === 'cable_matrix_not_uploaded')).toBe(true)

    const result = await api().commitIntake(job.id)
    expect(result.job.device_count).toBe(2) // ready + warning written; conflict skipped
    expect(result.skipped_conflicts).toEqual([
      expect.objectContaining({
        kind: 'epif',
        row_number: 3,
        hostname: 'CONFLICT-sw',
        messages: [expect.objectContaining({ code: 'hostname_conflict' })],
      }),
    ])
    expect(result.warnings.some((w) => w.item_type === 'missing_position' && w.hostname === 'leaf-04')).toBe(true)
    expect(result.items.some((i) => i.item_type === 'missing_position' && i.status === 'open')).toBe(true)
    expect(result.items.some((i) => i.item_type === 'other' && i.hostname === 'CONFLICT-sw')).toBe(true)
    expect(result.items.some((i) => i.item_type === 'cable_matrix_not_uploaded')).toBe(true)
    expect(result.open_item_count).toBe(3)
    expect((await api().getJob(job.id)).device_count).toBe(2)

    const deferred = await api().deferItem(job.id, result.items.find((i) => i.item_type === 'missing_position')!.id, 'fill later')
    expect(deferred.status).toBe('deferred')
    expect(deferred.deferred_by).toBeTruthy()
    const open = await api().listOpenItems(job.id, 'unresolved')
    expect(open.total).toBe(3)
    expect(open.items.filter((i) => i.status === 'deferred')).toHaveLength(1)
  })
})

describe('abandon', () => {
  it('deletes an empty job and refuses one with committed work', async () => {
    const empty = await api().createJob('DCREQ0005001')
    await api().abandonJob(empty.id)
    await expect(api().getJob(empty.id)).rejects.toMatchObject({ status: 404 })

    const job = await api().createJob('DCREQ0005002')
    await api().stageImport(job.id, 'epif', csv('hostname,result\nleaf-01,ready\n'))
    await api().commitIntake(job.id)
    await expect(api().abandonJob(job.id)).rejects.toMatchObject({ status: 409, code: 'job_not_empty' })
    expect((await api().getJob(job.id)).status).toBe('open')
  })
})
