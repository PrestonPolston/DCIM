import { describe, expect, it } from 'vitest'
import {
  PARKED_MESSAGES, RECENTLY_RETIRED_DAYS, STALE_DRAFT_DAYS, composeDeviceIssues, composeProfileHealth,
  composeSearch, composeSummary, daysLabel, daysSince, defaultParked, parseApiDate,
} from './home'
import { PROFILE_FIXTURES, UNPLACED_FIXTURES, fixtureSummary } from './home.mock'
import { installMockApi, resetAuth, seedDb, type Db } from '../test/mockApi'
import { setCsrfToken } from './client'

const NOW = Date.parse('2026-11-11T14:00:00Z')

describe('composeProfileHealth', () => {
  it('counts needs-review, stale drafts (≥ 14 d) and recently retired (30 d) and caps lists', () => {
    const h = composeProfileHealth(PROFILE_FIXTURES, NOW)
    expect(h.counts).toEqual({ draft: 1, published: 3, retired: 1 })
    expect(h.needs_review).toBe(2)
    expect(h.stale_drafts).toBe(1)
    expect(h.recently_retired).toBe(1)
    expect(h.dates_available).toBe(true)
    expect(h.needs_review_items.map((p) => p.name)).toEqual(['Generic 1U server', 'Generic 48-port switch'])
    expect(h.stale_draft_items[0]).toMatchObject({ name: 'Acme X100', status: 'draft' })
    expect(daysSince(h.stale_draft_items[0].updated_at, NOW)).toBeGreaterThanOrEqual(STALE_DRAFT_DAYS)
    expect(daysSince(h.recently_retired_items[0].retired_at, NOW)).toBeLessThanOrEqual(RECENTLY_RETIRED_DAYS)
    expect(h.recently_changed[0].name).toBe('Dell R650')
  })

  it('does not invent stale or recent-retired counts when dates are missing', () => {
    const rows = PROFILE_FIXTURES.map((row) => {
      const { updated_at, published_at, retired_at, ...rest } = row
      void updated_at; void published_at; void retired_at
      return rest
    })
    const h = composeProfileHealth(rows, NOW)
    expect(h.dates_available).toBe(false)
    expect(h.needs_review).toBe(2)
    expect(h.stale_drafts).toBe(0)
    expect(h.stale_draft_items).toEqual([])
    expect(h.recently_retired).toBe(0)
    expect(h.counts.draft).toBe(1)
    expect(h.counts.retired).toBe(1)
  })

  it('empty catalog is healthy', () => {
    const h = composeProfileHealth([], NOW)
    expect(h.needs_review + h.stale_drafts + h.recently_retired).toBe(0)
    expect(h.counts).toEqual({ draft: 0, published: 0, retired: 0 })
  })
})

describe('composeDeviceIssues', () => {
  it('maps host_name to hostname and caps the list at 10', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ id: i + 1, host_name: `host-${i + 1}`, status: 'install' as const }))
    const d = composeDeviceIssues(many, 12)
    expect(d.no_position.count).toBe(12)
    expect(d.no_position.items).toHaveLength(10)
    expect(d.no_position.items[0]).toEqual({ id: 1, hostname: 'host-1', status: 'install' })
  })

  it('prefers the summary field hostname when present', () => {
    expect(composeDeviceIssues(UNPLACED_FIXTURES).no_position.items[0].hostname).toBe('r01c03-srv-09')
  })
})

describe('parked tiles and dates', () => {
  it('default parked map uses not_available and the mock badge copy', () => {
    const p = defaultParked()
    expect(p.current_jobs).toEqual({ status: 'not_available', message: PARKED_MESSAGES.current_jobs })
    expect(p.dcreq_search.status).toBe('not_available')
    expect(Object.keys(p)).toEqual(expect.arrayContaining(['overdue_jobs', 'current_jobs', 'recent_dcreqs', 'held_imports', 'workload', 'power_issues', 'dcreq_search']))
  })

  it('parses offset-less timestamps as UTC and offset-bearing ones as given', () => {
    expect(parseApiDate('2026-11-11 14:00:00')?.toISOString()).toBe('2026-11-11T14:00:00.000Z')
    expect(parseApiDate('2026-11-11T08:00:00-06:00')?.toISOString()).toBe('2026-11-11T14:00:00.000Z')
    expect(daysLabel(0)).toBe('today')
    expect(daysLabel(1)).toBe('1 day ago')
    expect(daysLabel(22)).toBe('22 days ago')
  })

  it('fixture summary omits admin when asked', () => {
    expect(fixtureSummary({ includeAdmin: false }).admin).toBeUndefined()
    expect(fixtureSummary().admin?.profile_health.needs_review).toBe(2)
  })
})

describe('compose from existing endpoints', () => {
  it('builds admin summary from /profiles and unplaced /devices, and parks job tiles', async () => {
    resetAuth()
    setCsrfToken('csrf-1')
    const db: Db = seedDb()
    db.devices.push({ id: 10, host_name: 'spare-01', status: 'install', serial_number: null, rack_id: null, position_u: null, face: 'front', device_type_id: 1 })
    installMockApi(db)
    const s = await composeSummary(true, NOW)
    expect(s.parked.current_jobs.status).toBe('not_available')
    expect(s.admin?.device_issues.no_position.items.some((d) => d.hostname === 'spare-01')).toBe(true)
    expect(s.admin?.profile_health.counts.published).toBeGreaterThanOrEqual(1)
    const tech = await composeSummary(false, NOW)
    expect(tech.admin).toBeUndefined()
  })

  it('keeps the other tile when one endpoint fails', async () => {
    resetAuth()
    setCsrfToken('csrf-1')
    installMockApi(seedDb(), (method, path) =>
      method === 'GET' && path === '/profiles' ? new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }) : undefined)
    const s = await composeSummary(true, NOW)
    expect(s.errors?.profile_health).toMatch(/500|boom|Failed/i)
    expect(s.admin?.device_issues).toBeDefined()
  })

  it('fans search out to device, cabinet, row and hall and parks DCREQ', async () => {
    resetAuth()
    setCsrfToken('csrf-1')
    installMockApi(seedDb())
    const r = await composeSearch('Hall')
    expect(r.halls.some((h) => h.label === 'Hall 2' && h.href === '/halls/1')).toBe(true)
    expect(r.dcreqs).toEqual({ status: 'not_available', message: PARKED_MESSAGES.dcreq_search })
    const cab = await composeSearch('R12')
    expect(cab.cabinets).toEqual([expect.objectContaining({ kind: 'cabinet', label: 'R12', href: '/cabinets/12' })])
    const row = await composeSearch('Row')
    expect(row.rows).toEqual([expect.objectContaining({ kind: 'row', label: 'Row 3', href: '/halls/1/rows/1' })])
    const dev = await composeSearch('web-01')
    expect(dev.devices[0]).toMatchObject({ kind: 'device', label: 'web-01', href: '/cabinets/12?device=1' })
    const serial = await composeSearch('SN-A1')
    expect(serial.devices[0].label).toBe('web-01')
    const none = await composeSearch('x')
    expect(none.devices).toEqual([])
  })
})
