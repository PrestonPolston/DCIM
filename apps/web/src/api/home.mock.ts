// Fixtures matching GET /home/summary (docs/API.md on feat/home-summary).
import {
  PARKED, composeDeviceIssues, composeProfileHealth, parkedMyWork, profileDisplayName,
  type HomeSearchResults, type HomeSummary, type ParkedTile, type ProfileHealth, type DeviceIssues,
} from './home'

const NOW = Date.parse('2026-11-11T14:00:00Z')

/** Sample GET /profiles rows, including published_at / retired_at / updated_at (Z). */
export const PROFILE_FIXTURES: Record<string, unknown>[] = [
  {
    id: 11, device_type_id: 1, name: 'Default', is_default: true, u_height: 1, is_full_depth: true,
    manufacturer: 'Generic', model: '1U server', status: 'published', usable: false,
    usable_issues: ['rear_image_missing'], device_count: 14,
    updated_at: '2026-11-01T00:00:00Z', published_at: '2026-10-01T00:00:00Z', retired_at: null,
  },
  {
    id: 12, device_type_id: 2, name: 'Default', is_default: true, u_height: 1, is_full_depth: false,
    manufacturer: 'Generic', model: '48-port switch', status: 'published', usable: false,
    usable_issues: ['orientation_missing'], device_count: 6,
    updated_at: '2026-11-05T00:00:00Z', published_at: '2026-10-02T00:00:00Z', retired_at: null,
  },
  {
    id: 13, device_type_id: 1, name: 'Default', is_default: true, u_height: 2, is_full_depth: true,
    manufacturer: 'Acme', model: 'X100', status: 'draft', usable: false, usable_issues: ['profile_draft'],
    device_count: 0, updated_at: '2026-10-20T00:00:00Z', published_at: null, retired_at: null,
  },
  {
    id: 14, device_type_id: 1, name: 'Old', is_default: false, u_height: 42, is_full_depth: true,
    manufacturer: 'Acme', model: 'Racks 42U', status: 'retired', usable: false, usable_issues: ['profile_retired'],
    device_count: 0, updated_at: '2026-11-05T00:00:00Z', published_at: '2026-01-01T00:00:00Z', retired_at: '2026-11-05T00:00:00Z',
  },
  {
    id: 15, device_type_id: 1, name: 'Default', is_default: true, u_height: 2, is_full_depth: true,
    manufacturer: 'Dell', model: 'R650', status: 'published', usable: true, usable_issues: [],
    device_count: 3, updated_at: '2026-11-10T00:00:00Z', published_at: '2026-09-01T00:00:00Z', retired_at: null,
  },
]

export const UNPLACED_FIXTURES = [
  { id: 21, hostname: 'r01c03-srv-09', status: 'install', updated_at: '2026-11-10T14:00:00Z' },
  { id: 22, hostname: 'gpu-spare-1', status: 'install', updated_at: '2026-11-10T13:00:00Z' },
  { id: 23, hostname: 'lab-fw-02', status: 'active', updated_at: '2026-11-09T14:00:00Z' },
]

export function fixtureProfileHealth(now = NOW): ProfileHealth {
  return composeProfileHealth(PROFILE_FIXTURES as (Record<string, unknown> & { id: number; name: string })[], now)
}

export function fixtureDeviceIssues(): DeviceIssues {
  return composeDeviceIssues(UNPLACED_FIXTURES, UNPLACED_FIXTURES.length)
}

export function fixtureSummary(opts: { includeAdmin?: boolean; now?: number } = {}): HomeSummary {
  const includeAdmin = opts.includeAdmin ?? true
  const now = opts.now ?? NOW
  const summary: HomeSummary = {
    generated_at: new Date(now).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    my_work: parkedMyWork(),
  }
  if (includeAdmin) {
    summary.admin = { profile_health: fixtureProfileHealth(now), device_issues: fixtureDeviceIssues(), workload: PARKED.workload }
  }
  return summary
}

export const SEARCH_FIXTURES: HomeSearchResults = {
  devices: [{ kind: 'device', id: 1, label: 'web-01', href: '/cabinets/12?device=1', subtitle: 'SN SN-A1' }],
  cabinets: [{ kind: 'cabinet', id: 12, label: 'R12', href: '/cabinets/12' }],
  rows: [{ kind: 'row', id: 1, label: 'Row 3', href: '/halls/1/rows/1' }],
  halls: [{ kind: 'hall', id: 1, label: 'Hall 2', href: '/halls/1' }],
  dcreqs: PARKED.dcreq_search,
}

export { PARKED, profileDisplayName }
export type { ParkedTile }
