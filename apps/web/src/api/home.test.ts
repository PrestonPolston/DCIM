import { describe, expect, it } from 'vitest'
import {
  HOME_LIST_LIMIT, PARKED, RECENTLY_RETIRED_DAYS, STALE_DRAFT_DAYS, composeDeviceIssues, composeProfileHealth,
  composeSearch, composeSummary, daysLabel, daysSince, hrefForFilter, parkedMyWork, parseApiDate, profileDisplayName,
  searchHref, searchSubtitle, SEARCH_DEFAULT_LIMIT, SEARCH_MIN,
} from './home'
import { PROFILE_FIXTURES, UNPLACED_FIXTURES, fixtureSummary } from './home.mock'
import { installMockApi, resetAuth, seedDb, type Db } from '../test/mockApi'
import { setCsrfToken } from './client'

const NOW = Date.parse('2026-11-11T14:00:00Z')
const asRows = () => PROFILE_FIXTURES as (Record<string, unknown> & { id: number; name: string })[]

describe('composeProfileHealth', () => {
  it('matches the summary shape: by_status, capped lists, by_issue, display names and filters', () => {
    const h = composeProfileHealth(asRows(), NOW)
    expect(h.key).toBe('profile_health')
    expect(h.by_status).toEqual({ draft: 1, published: 3, retired: 1 })
    expect(h.needs_review.count).toBe(2)
    expect(h.needs_review.truncated).toBe(false)
    expect(h.needs_review.filter).toBe('status=published&usable=false')
    expect(h.needs_review.by_issue).toEqual({ rear_image_missing: 1, orientation_missing: 1 })
    expect(h.needs_review.items).toEqual([
      { id: 12, name: 'Generic 48-port switch · Default', usable_issue: 'orientation_missing', usable_issues: ['orientation_missing'] },
      { id: 11, name: 'Generic 1U server · Default', usable_issue: 'rear_image_missing', usable_issues: ['rear_image_missing'] },
    ])
    expect(h.stale_drafts).toMatchObject({ count: 1, truncated: false, filter: 'status=draft' })
    expect(h.stale_drafts.items[0]).toEqual({ id: 13, name: 'Acme X100 · Default', updated_at: '2026-10-20T00:00:00Z' })
    expect(daysSince(h.stale_drafts.items[0].updated_at, NOW)).toBeGreaterThanOrEqual(STALE_DRAFT_DAYS)
    expect(h.recently_retired.items[0]).toEqual({ id: 14, name: 'Acme Racks 42U · Old', retired_at: '2026-11-05T00:00:00Z' })
    expect(daysSince(h.recently_retired.items[0].retired_at, NOW)).toBeLessThanOrEqual(RECENTLY_RETIRED_DAYS)
    expect(h.recently_changed.count).toBe(5)
    expect(h.recently_changed.items[0]).toMatchObject({ id: 15, name: 'Dell R650 · Default', status: 'published', retired_at: null })
    expect(h.recently_changed.items).toHaveLength(Math.min(5, HOME_LIST_LIMIT))
  })

  it('does not invent stale or recent-retired counts when dates are missing', () => {
    const rows = asRows().map((row) => {
      const { updated_at, published_at, retired_at, ...rest } = row
      void updated_at; void published_at; void retired_at
      return rest as typeof row
    })
    const h = composeProfileHealth(rows, NOW)
    expect(h.needs_review.count).toBe(2)
    expect(h.stale_drafts.count).toBe(0)
    expect(h.stale_drafts.items).toEqual([])
    expect(h.recently_retired.count).toBe(0)
    expect(h.by_status.draft).toBe(1)
  })

  it('marks truncated when more than 5 items and reports the full count', () => {
    const many = Array.from({ length: 8 }, (_, i) => ({
      id: 100 + i, device_type_id: 1, name: 'Default', is_default: true, u_height: 1, is_full_depth: true,
      manufacturer: 'Acme', model: `S${i}`, status: 'published', usable: false,
      usable_issues: ['rear_image_missing'], updated_at: '2026-11-01T00:00:00Z',
    }))
    const h = composeProfileHealth(many as (Record<string, unknown> & { id: number; name: string })[], NOW)
    expect(h.needs_review.count).toBe(8)
    expect(h.needs_review.truncated).toBe(true)
    expect(h.needs_review.items).toHaveLength(5)
  })

  it('empty catalog is healthy', () => {
    const h = composeProfileHealth([], NOW)
    expect(h.needs_review.count + h.stale_drafts.count + h.recently_retired.count).toBe(0)
    expect(h.by_status).toEqual({ draft: 0, published: 0, retired: 0 })
  })
})

describe('composeDeviceIssues', () => {
  it('maps host_name to hostname, caps at 10, and carries the official filter', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ id: i + 1, host_name: `host-${i + 1}`, status: 'install' as const, updated_at: '2026-11-10T00:00:00Z' }))
    const d = composeDeviceIssues(many, 12)
    expect(d.key).toBe('device_issues')
    expect(d.no_position).toMatchObject({ count: 12, truncated: true, filter: 'status=install&status=active&unplaced=true' })
    expect(d.no_position.items).toHaveLength(10)
    expect(d.no_position.items[0]).toEqual({ id: 1, hostname: 'host-1', status: 'install', updated_at: '2026-11-10T00:00:00Z' })
    expect(d.needs_power_assignment).toEqual(PARKED.needs_power_assignment)
    expect(d.port_conflicts.status).toBe('not_available')
    expect(d.open_power_mismatches.key).toBe('open_power_mismatches')
  })

  it('prefers the summary field hostname when present', () => {
    expect(composeDeviceIssues(UNPLACED_FIXTURES).no_position.items[0].hostname).toBe('r01c03-srv-09')
  })
})

describe('parked tiles, names and dates', () => {
  it('my_work and admin parked tiles use the official key + not_available + message', () => {
    const w = parkedMyWork()
    expect(w.jobs).toEqual({ key: 'jobs', status: 'not_available', message: 'Needs jobs/DCREQ logic.' })
    expect(w.held_imports.message).toBe('Held ePIF import rows are not in the API yet.')
    expect(PARKED.workload.key).toBe('workload')
    expect('count' in w.jobs).toBe(false)
  })

  it('formats profile names and filter hrefs the way the summary documents them', () => {
    expect(profileDisplayName('Acme', 'Srv', 'NoRear')).toBe('Acme Srv · NoRear')
    expect(hrefForFilter('/profiles', 'status=published&usable=false')).toBe('/profiles?status=published&usable=false')
    expect(hrefForFilter('/devices', 'status=install&status=active&unplaced=true')).toBe('/devices?status=install&status=active&unplaced=true')
  })

  it('parses offset-less timestamps as UTC and offset-bearing ones as given', () => {
    expect(parseApiDate('2026-11-11 14:00:00')?.toISOString()).toBe('2026-11-11T14:00:00.000Z')
    expect(parseApiDate('2026-11-11T08:00:00-06:00')?.toISOString()).toBe('2026-11-11T14:00:00.000Z')
    expect(daysLabel(0)).toBe('today')
    expect(daysLabel(1)).toBe('1 day ago')
    expect(daysLabel(22)).toBe('22 days ago')
  })

  it('fixture summary omits the admin key when asked', () => {
    expect(fixtureSummary({ includeAdmin: false })).not.toHaveProperty('admin')
    expect(fixtureSummary().admin?.profile_health.needs_review.count).toBe(2)
  })
})

describe('compose from existing endpoints', () => {
  it('builds an admin summary from /profiles and unplaced /devices, and parks job tiles', async () => {
    resetAuth()
    setCsrfToken('csrf-1')
    const db: Db = seedDb()
    db.devices.push({ id: 10, host_name: 'spare-01', status: 'install', serial_number: null, rack_id: null, position_u: null, face: 'front', device_type_id: 1 })
    installMockApi(db)
    const s = await composeSummary(true, NOW)
    expect(s.my_work.jobs.status).toBe('not_available')
    expect(s.admin?.device_issues.no_position.items.some((d) => d.hostname === 'spare-01')).toBe(true)
    expect(s.admin?.profile_health.by_status.published).toBeGreaterThanOrEqual(1)
    expect(s.admin?.workload.status).toBe('not_available')
    const tech = await composeSummary(false, NOW)
    expect(tech).not.toHaveProperty('admin')
  })

  it('composes GET /home/search groups for device, cabinet, row and hall and parks DCREQ', async () => {
    resetAuth()
    setCsrfToken('csrf-1')
    installMockApi(seedDb())
    const r = await composeSearch('Hall')
    expect(r.query).toBe('Hall')
    expect(r.generated_at).toMatch(/Z$/)
    const halls = r.groups.find((g) => g.key === 'halls')
    expect(halls?.items.some((h) => h.label === 'Hall 2' && h.id === 1)).toBe(true)
    expect(searchHref('halls', halls!.items[0])).toBe('/halls/1')
    expect(r.parked).toEqual([PARKED.dcreq_search])
    expect(PARKED.dcreq_search).toEqual({ key: 'dcreqs', status: 'not_available', message: 'DCREQ search is not available yet.' })
    const cab = await composeSearch('R12')
    const cabinets = cab.groups.find((g) => g.key === 'cabinets')
    expect(cabinets?.items).toEqual([expect.objectContaining({ label: 'R12', name: 'R12', id: 12 })])
    expect(searchHref('cabinets', cabinets!.items[0])).toBe('/cabinets/12')
    const row = await composeSearch('Row')
    const rows = row.groups.find((g) => g.key === 'rows')
    expect(rows?.items).toEqual([expect.objectContaining({ label: 'Row 3', name: 'Row 3', hall_id: 1, hall_name: null })])
    expect(searchHref('rows', rows!.items[0])).toBe('/halls/1/rows/1')
    const dev = await composeSearch('web-01')
    const devices = dev.groups.find((g) => g.key === 'devices')
    expect(devices?.items[0]).toMatchObject({ label: 'web-01', hostname: 'web-01', rack_id: 12 })
    expect(searchHref('devices', devices!.items[0])).toBe('/cabinets/12?device=1')
    const serial = await composeSearch('SN-A1')
    expect(serial.groups.find((g) => g.key === 'devices')?.items[0].label).toBe('web-01')
    const short = await composeSearch('x')
    expect(short.query).toBe('x')
    expect(short.groups.every((g) => g.items.length === 0 && g.count === 0 && !g.truncated)).toBe(true)
    expect(SEARCH_MIN).toBe(2)
    expect(SEARCH_DEFAULT_LIMIT).toBe(5)
  })

  it('marks a group truncated when the total is above the limit', async () => {
    resetAuth()
    setCsrfToken('csrf-1')
    const db = seedDb()
    for (let i = 0; i < 6; i++) db.racks.push({ id: 100 + i, row_id: 1, name: `Cab-${i}`, u_height: 42 })
    installMockApi(db)
    const r = await composeSearch('Cab', 5)
    const cabinets = r.groups.find((g) => g.key === 'cabinets')
    expect(cabinets).toMatchObject({ count: 6, truncated: true })
    expect(cabinets?.items).toHaveLength(5)
    const all = await composeSearch('Cab', 20)
    const full = all.groups.find((g) => g.key === 'cabinets')
    expect(full).toMatchObject({ count: 6, truncated: false })
    expect(full?.items).toHaveLength(6)
  })
})

describe('searchHref and searchSubtitle', () => {
  it('links placed and unplaced devices, cabinets, rows and halls, and labels No position', () => {
    const placed = { id: 1, label: 'web-01', hostname: 'web-01', serial: 'SN-A1', status: 'active', rack_id: 12, rack_name: 'R12', position_u: 20 }
    expect(searchHref('devices', placed)).toBe('/cabinets/12?device=1')
    expect(searchSubtitle('devices', placed)).toBe('R12 · RU20 · SN SN-A1')
    const unplaced = { id: 10, label: 'spare-01', hostname: 'spare-01', serial: null, status: 'install', rack_id: null, rack_name: null, position_u: null }
    expect(searchHref('devices', unplaced)).toBe('/devices?q=spare-01')
    expect(searchSubtitle('devices', unplaced)).toBe('No position')
    const cabinet = { id: 12, label: 'R12', name: 'R12', row_id: 1, row_name: 'Row 3', hall_id: 1, hall_name: 'Hall 2' }
    expect(searchHref('cabinets', cabinet)).toBe('/halls/1/cabinets/12')
    expect(searchSubtitle('cabinets', cabinet)).toBe('Row 3 · Hall 2')
    const row = { id: 1, label: 'Row 3', name: 'Row 3', hall_id: 1, hall_name: 'Hall 2', site_id: 1, site_name: 'Site A' }
    expect(searchHref('rows', row)).toBe('/halls/1/rows/1')
    expect(searchSubtitle('rows', row)).toBe('Hall 2 · Site A')
    const rowNoHall = { id: 1, label: 'Row 3', name: 'Row 3', hall_id: null, hall_name: null, site_id: 1, site_name: 'Site A' }
    expect(searchHref('rows', rowNoHall)).toBeUndefined()
    expect(searchSubtitle('rows', rowNoHall)).toBe('Site A')
    const hall = { id: 1, label: 'Hall 2', name: 'Hall 2', site_id: 1, site_name: 'Site A' }
    expect(searchHref('halls', hall)).toBe('/halls/1')
    expect(searchSubtitle('halls', hall)).toBe('Site A')
  })
})
