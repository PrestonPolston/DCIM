import { beforeEach, describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { friendlyMessage, errorDetail, stripPydanticText, formatValidationErrors, noteFieldError, textFieldError, jobTextViolation, textRejectionCopy } from './errors'
import {
  DCREQ_PATTERN,
  JOB_INTAKE_API,
  JOB_OVERDUE_DAYS,
  daysBetween,
  duplicateExisting,
  isDuplicateDcreq,
  isJobHasOpenItems,
  isJobOverdue,
  isValidDcreq,
  closeOpenItemsWarning,
  cableTrail,
  countLabel,
  devicePageHref,
  fieldLabel,
  itemTypeLabel,
  jobHref,
  jobIntakeApi,
  jobOverdueAt,
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
    expect(job.unresolved_count).toBe(2)
    expect(job.unresolved_by_type).toEqual({ epif_not_uploaded: 1, cable_matrix_not_uploaded: 1 })
    expect((await api().listOpenItems(job.id, 'unresolved')).items.map((i) => i.item_type).sort()).toEqual([
      'cable_matrix_not_uploaded', 'epif_not_uploaded',
    ])
    expect(jobHref(job)).toBe('/jobs/DCREQ0001234')
  })

  it('returns 422 dcreq_format and creates nothing when the DCREQ is invalid', async () => {
    await expect(api().createJob('nope')).rejects.toMatchObject({ status: 422, code: 'dcreq_format' })
    expect((await api().listJobs()).total).toBe(0)
  })

  it('hard-stops a duplicate DCREQ with 409 job_exists and the existing job', async () => {
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
    expect((err as ApiError).code).toBe('job_exists')
    expect(duplicateExisting(err)).toEqual({
      id: first.id, dcreq: 'DCREQ0001234', name: 'DCREQ0001234', status: 'open', is_job: true, deleted: false,
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
    expect(isJobOverdue({ status: 'open', opened_at: '2026-11-01T13:00:00Z', overdue_at: '2026-11-12T12:59:59Z' }, now)).toBe(true)
    expect(isJobOverdue({ status: 'open', opened_at: '2026-09-01T13:00:00Z', overdue_at: '2026-11-12T13:00:00Z' }, now)).toBe(false)
    expect(jobOverdueAt('2026-10-13T13:00:00Z')).toBe('2026-11-12T13:00:00.000Z')
    expect(daysBetween('2026-11-07T13:00:00Z', now)).toBe(5)
    expect(JOB_OVERDUE_DAYS).toBe(30)
  })

  it('lists overdue jobs and does not reset the clock on reopen', async () => {
    seedMockJob({ dcreq: 'DCREQ0002001', name: 'Old leaf', opened_at: agoZ(40) })
    const listed = await api().listJobs({ overdue: true })
    expect(listed.total).toBe(1)
    expect(listed.items[0].overdue).toBe(true)
    expect(listed.items[0].overdue_at).toBeTruthy()
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
  it('refuses close with 409 job_has_open_items, then closes when acknowledged', async () => {
    const job = await api().createJob('DCREQ0003001')
    let err: unknown
    try {
      await api().closeJob(job.id)
    } catch (e) {
      err = e
    }
    expect(isJobHasOpenItems(err)).toBe(true)
    expect((err as ApiError).status).toBe(409)
    expect(errorDetail((err as ApiError).detail)?.unresolved_count).toBe(2)
    expect((await api().getJob(job.id)).status).toBe('open')
    const result = await api().closeJob(job.id, { acknowledge_open_items: true })
    expect(result.job.status).toBe('closed')
    expect(result.job.current).toBe(false)
    expect(result.job.overdue).toBe(false)
    expect(result.job.closed_at).toMatch(/Z$/)
    expect(result.warning).toEqual({
      code: 'job_has_open_items',
      unresolved_count: 2,
      message: 'This job still has 2 unresolved items.',
    })
  })

  it('closes with a null warning when the queue is empty', async () => {
    const job = await api().createJob('DCREQ0003002')
    const pending = await api().listOpenItems(job.id, 'unresolved')
    for (const item of pending.items) await api().resolveItem(job.id, item.id)
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
    expect(staged.counts).toMatchObject({ total: 3, ready: 1, warning: 1, held: 0, conflict: 1 })
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
    expect(deferred.item.status).toBe('deferred')
    expect(deferred.item.deferred_by).toBeTruthy()
    expect(deferred.job.unresolved_count).toBe(result.open_item_count)
    expect(deferred.job.deferred_count).toBeGreaterThan(0)
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

describe('item labels and close warning copy', () => {
  it('uses readable labels instead of raw type names', () => {
    expect(itemTypeLabel('epif_not_uploaded')).toBe('ePIF not uploaded')
    expect(itemTypeLabel('cable_matrix_not_uploaded')).toBe('Cable matrix not uploaded')
    expect(itemTypeLabel('missing_position')).toBe('Missing position')
    expect(itemTypeLabel('pdu_missing')).toBe('Missing PDU')
    expect(itemTypeLabel('unresolved_device')).toBe('Unresolved device')
    expect(itemTypeLabel('unresolved_hop')).toBe('Unresolved hop')
    expect(itemTypeLabel('missing_trail')).toBe('Missing trail')
    expect(itemTypeLabel('missing_cable_label')).toBe('Missing cable label')
    expect(itemTypeLabel('media_missing')).toBe('Missing media')
    expect(itemTypeLabel('ip_missing')).toBe('Missing IP')
    expect(itemTypeLabel('port_in_use')).toBe('Port in use')
    expect(itemTypeLabel('hop_in_use')).toBe('Hop in use')
    expect(itemTypeLabel('cable_label_conflict')).toBe('Cable label conflict')
  })

  it('uses readable field labels and pluralizes counts', () => {
    expect(fieldLabel('position_u')).toBe('position (U)')
    expect(fieldLabel('psu_1')).toBe('PSU 1')
    expect(fieldLabel('psu_2')).toBe('PSU 2')
    expect(fieldLabel('unknown_col')).toBe('unknown col')
    expect(countLabel(0, 'device')).toBe('0 devices')
    expect(countLabel(1, 'device')).toBe('1 device')
    expect(countLabel(2, 'device')).toBe('2 devices')
    expect(countLabel(1, 'connection')).toBe('1 connection')
  })

  it('links to the devices page when an item has a device', () => {
    expect(devicePageHref({ device_id: 7, hostname: 'web11' })).toBe('/devices?q=web11')
    expect(devicePageHref({ device_id: 7, hostname: null })).toBe('/devices')
    expect(devicePageHref({ device_id: null, hostname: 'web11' })).toBeNull()
  })

  it('uses the friendly errors.ts text for closeOpenItemsWarning, not the API field name', () => {
    const err = new ApiError(409, 'Close again with acknowledge_open_items=true to close it anyway.', {
      detail: { code: 'job_has_open_items', message: 'Close again with acknowledge_open_items=true to close it anyway.', unresolved_count: 2 },
    })
    const warning = closeOpenItemsWarning(err)
    expect(warning?.message).toBe('This job still has 2 unresolved items. You can close it anyway.')
    expect(warning?.message).not.toMatch(/acknowledge_open_items/)
    expect(warning?.unresolved_count).toBe(2)
  })
})

describe('fill item', () => {
  it('writes the field value first and then resolves the item', async () => {
    const job = await api().createJob('DCREQ0006001')
    const seeded = (await api().listOpenItems(job.id, 'unresolved')).items[0]
    // add a field-bearing item
    const { seedMockOpenItem } = await import('./jobIntake.mock')
    const item = seedMockOpenItem({
      job_id: job.id,
      item_type: 'missing_position',
      hostname: 'leaf-04',
      target_field: 'position_u',
      import_row_id: 99,
    })
    const filled = await api().fillItem(job.id, item.id, '42')
    expect(filled.item.status).toBe('resolved')
    expect(filled.item.filled_value).toBe('42')
    expect(filled.item.note).toBe('position_u=42')
    expect(filled.job.unresolved_count).toBe(2) // two not-uploaded items remain; seeded item resolved
    expect((await api().getJob(job.id)).unresolved_count).toBe(2)
    void seeded
  })
})

describe('cable-matrix mock import', () => {
  it('requires A Name, A Port, Z Name and Z Port, and accepts A/Z aliases', async () => {
    const job = await api().createJob('DCREQ0007001')
    await expect(api().stageImport(job.id, 'cable_matrix', csv('A Name,A Port,Z Name\nsw1,Eth1,srv1\n', 'cables.csv'))).rejects.toMatchObject({
      status: 422, code: 'missing_columns',
    })
    const staged = await api().stageImport(
      job.id,
      'cable_matrix',
      csv('A Side Hostname,A Port,Z Name,Z End Interface\nsw1,Eth1,srv1,eth0\n', 'cables.csv'),
    )
    expect(staged.kind).toBe('cable_matrix')
    expect(staged.counts.total).toBe(1)
    expect((staged.counts.ready ?? 0) + (staged.counts.warning ?? 0)).toBe(1)
    expect(staged.rows?.[0]).toMatchObject({ a: 'sw1:Eth1', z: 'srv1:eth0' })
    expect(['ready', 'warning']).toContain(staged.rows?.[0].result)
  })

  it('commits resolved rows, holds an unresolved device, skips port_in_use, and keeps cable_trail', async () => {
    const job = await api().createJob('DCREQ0007002')
    const body = [
      'ID,Trail,Cable Label,A Name,A Port,Z Name,Z Port',
      'C1,T-1,CAB-1,sw1,Eth1,srv1,eth0',
      'C2,T-1,CAB-2,sw1,Eth2,ghost,eth0',
      'C3,T-1,CAB-3,sw1,Eth3,srv1,eth0',
      '',
    ].join('\n')
    const staged = await api().stageImport(job.id, 'cable_matrix', csv(body, 'cables.csv'))
    expect(staged.rows?.map((r) => r.result)).toEqual(['ready', 'held', 'conflict'])
    expect(staged.rows?.[1].messages[0].code).toBe('unresolved_device')
    expect(staged.rows?.[2].messages[0].code).toBe('port_in_use')
    const preview = await api().previewJob(job.id)
    expect(preview.cable_matrix?.id).toBe(staged.id)
    expect(preview.pending_items.some((i) => i.item_type === 'missing_hostname')).toBe(true)
    const result = await api().commitIntake(job.id)
    expect(result.job.connection_count).toBe(1)
    expect(result.committed).toEqual([
      expect.objectContaining({ kind: 'cable_matrix', row_number: 1, a: 'sw1:Eth1', z: 'srv1:eth0', cable_label: 'CAB-1', connection_id: expect.any(Number) }),
    ])
    expect(result.held).toEqual([
      expect.objectContaining({ row_number: 2, z: 'ghost:eth0', reasons: [expect.objectContaining({ code: 'unresolved_device' })] }),
    ])
    expect(result.skipped_conflicts).toEqual([
      expect.objectContaining({ row_number: 3, z: 'srv1:eth0', messages: [expect.objectContaining({ code: 'port_in_use' })] }),
    ])
    const heldItem = result.items.find((i) => i.item_type === 'missing_hostname')
    expect(heldItem).toMatchObject({ cable_label: 'CAB-2', source: 'cable_matrix' })
    expect(cableTrail(heldItem!)).toBe('T-1')
    expect(result.items.find((i) => i.item_type === 'cable_matrix_not_uploaded')?.status).toBe('resolved')
  })
})

describe('note validation copy', () => {
  it('uses friendly copy for invalid_text and formula_prefix', () => {
    expect(friendlyMessage({ code: 'invalid_text', message: 'raw', field: 'note' }, 422)).toBe("This note has characters that aren't allowed.")
    expect(friendlyMessage({ code: 'formula_prefix', message: 'raw', field: 'note' }, 422)).toBe("This note can't start with =, +, - or @.")
    expect(friendlyMessage({ code: 'formula_prefix', message: 'raw', field: 'dcreq' }, 422)).toBe("This DCREQ can't start with =, +, - or @.")
    expect(friendlyMessage({ code: 'formula_prefix', message: 'raw', field: 'name' }, 422)).toBe("This name can't start with =, +, - or @.")
    expect(friendlyMessage({ code: 'invalid_text', message: 'raw', field: 'description' }, 422)).toBe("This description has characters that aren't allowed.")
    expect(textRejectionCopy('formula_prefix', 'description')).toBe("This description can't start with =, +, - or @.")
  })

  it('allows formula-prefixed and multiline notes, and rejects those on name/dcreq/description', () => {
    expect(jobTextViolation('note', '=SUM(A1)\nSecond', 'note')).toBeNull()
    expect(jobTextViolation('note', 'ok\tindented', 'note')).toBeNull()
    expect(jobTextViolation('note', 'bad\u0001', 'note')?.code).toBe('invalid_text')
    expect(jobTextViolation('name', '=Leaf', 'single_line')?.code).toBe('formula_prefix')
    expect(jobTextViolation('dcreq', '=DCREQ0001234', 'single_line')?.field).toBe('dcreq')
    expect(jobTextViolation('description', 'line1\nline2', 'single_line')?.code).toBe('invalid_text')
  })

  it('strips pydantic validation text as a fallback', () => {
    expect(stripPydanticText('Value error, note must not contain control characters')).toBe("This note has characters that aren't allowed.")
    expect(stripPydanticText('Value error, note must not contain control characters other than line breaks')).toBe("This note has characters that aren't allowed.")
    expect(stripPydanticText('note must not start with = + - @ (spreadsheet formula)')).toBe("This note can't start with =, +, - or @.")
    expect(formatValidationErrors([
      { type: 'value_error', loc: ['body'], msg: 'Value error, note must not contain control characters' },
    ])).toBe("This note has characters that aren't allowed.")
    const coded = new ApiError(422, 'raw', { detail: { code: 'invalid_text', message: 'raw', field: 'note' } })
    expect(noteFieldError(coded)).toBe("This note has characters that aren't allowed.")
    const pydantic = new ApiError(422, ': Value error, note must not contain control characters', {
      detail: [{ type: 'value_error', loc: ['body'], msg: 'Value error, note must not contain control characters' }],
    })
    expect(noteFieldError(pydantic)).toBe("This note has characters that aren't allowed.")
  })
})

describe('job text fields', () => {
  it('rejects a formula-prefixed job name and description without rewriting the value', async () => {
    await expect(api().createJob('DCREQ0008001', { name: '=Leaf' })).rejects.toMatchObject({
      status: 422, code: 'formula_prefix',
    })
    const err = await api().createJob('DCREQ0008001', { name: '=Leaf' }).catch((e) => e)
    expect(errorDetail(err.detail)?.field).toBe('name')
    expect(textFieldError(err, 'name')).toBe("This name can't start with =, +, - or @.")
    await expect(api().createJob('DCREQ0008001', { description: '-48V writeup' })).rejects.toMatchObject({
      status: 422, code: 'formula_prefix',
    })
    const ok = await api().createJob('DCREQ0008001', { name: 'Leaf refresh', description: 'Normal text' })
    expect(ok.name).toBe('Leaf refresh')
    expect(ok.description).toBe('Normal text')
    const resolved = await api().resolveItem(ok.id, (await api().listOpenItems(ok.id, 'unresolved')).items[0].id, '-48V DC feed\nsecond')
    expect(resolved.item.note).toMatch(/-48V DC feed/)
    expect(resolved.item.note).toMatch(/second/)
  })
})
