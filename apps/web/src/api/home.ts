// Home-page adapter for GET /home/summary and GET /home/search (docs/API.md on feat/home-summary).
// HOME_API.live defaults to true; tests flip it off and compose the same shapes
// from existing list endpoints (summary: /profiles, /devices; search: /devices, /racks, /rows, /halls).
import { useQuery } from '@tanstack/react-query'
import { ApiError, listPage, send } from './client'
import { needsReview, toUiProfile, type ProfileListItem, type ProfileStatus } from './profiles'
import type { Device, Hall, Rack, Row } from './types'

export const HOME_API = {
  /** true = GET /home/summary; false = compose the same shape from existing list endpoints. */
  live: true,
}

export const STALE_DRAFT_DAYS = 14
export const RECENTLY_RETIRED_DAYS = 30
export const HOME_LIST_LIMIT = 5
export const UNPOSITIONED_DEVICE_LIMIT = 10
export const SEARCH_MIN = 2
export const SEARCH_DEFAULT_LIMIT = 5
export const SEARCH_MAX_LIMIT = 20

export interface ParkedTile { key: string; status: 'not_available'; message: string }

export const PARKED = {
  jobs: { key: 'jobs', status: 'not_available', message: 'Needs jobs/DCREQ logic.' } as ParkedTile,
  dcreqs: { key: 'dcreqs', status: 'not_available', message: 'Needs jobs/DCREQ logic.' } as ParkedTile,
  held_imports: { key: 'held_imports', status: 'not_available', message: 'Held ePIF import rows are not in the API yet.' } as ParkedTile,
  workload: { key: 'workload', status: 'not_available', message: 'Needs jobs/DCREQ logic.' } as ParkedTile,
  needs_power_assignment: { key: 'needs_power_assignment', status: 'not_available', message: 'Needs device_psu_assignments; devices.power_assignment is free text only.' } as ParkedTile,
  port_conflicts: { key: 'port_conflicts', status: 'not_available', message: 'Port conflicts are refused at write time; there is no stored flag.' } as ParkedTile,
  open_power_mismatches: { key: 'open_power_mismatches', status: 'not_available', message: 'The power_mismatches table and route are not built.' } as ParkedTile,
  dcreq_search: { key: 'dcreqs', status: 'not_available', message: 'DCREQ search is not available yet.' } as ParkedTile,
}

export function parkedMyWork(): MyWork {
  return { jobs: PARKED.jobs, dcreqs: PARKED.dcreqs, held_imports: PARKED.held_imports }
}

/** `"<manufacturer> <model> · <profile name>"` — the summary's `name` field. */
export function profileDisplayName(manufacturer: string, model: string, name: string): string {
  return `${manufacturer} ${model} · ${name}`
}

export function hrefForFilter(path: '/profiles' | '/devices', filter: string): string {
  return `${path}?${filter}`
}

export interface NeedsReviewItem { id: number; name: string; usable_issue: string | null; usable_issues: string[] }
export interface StaleDraftItem { id: number; name: string; updated_at: string }
export interface RecentlyRetiredItem { id: number; name: string; retired_at: string }
export interface RecentlyChangedItem {
  id: number
  name: string
  status: ProfileStatus
  updated_at: string
  published_at: string | null
  retired_at: string | null
}
export interface UnpositionedDevice { id: number; hostname: string; status: string; updated_at: string }

export interface CappedList<T> { count: number; truncated: boolean; items: T[]; filter?: string }
export interface NeedsReviewList extends CappedList<NeedsReviewItem> {
  by_issue: { rear_image_missing: number; orientation_missing: number }
  filter: string
}
export interface StaleDraftsList extends CappedList<StaleDraftItem> { filter: string }
export interface RecentlyRetiredList extends CappedList<RecentlyRetiredItem> { filter: string }
export type RecentlyChangedList = CappedList<RecentlyChangedItem>
export interface UnpositionedList extends CappedList<UnpositionedDevice> { filter: string }

export interface ProfileHealth {
  key: 'profile_health'
  by_status: { draft: number; published: number; retired: number }
  needs_review: NeedsReviewList
  stale_drafts: StaleDraftsList
  recently_retired: RecentlyRetiredList
  recently_changed: RecentlyChangedList
}
export interface DeviceIssues {
  key: 'device_issues'
  no_position: UnpositionedList
  needs_power_assignment: ParkedTile
  port_conflicts: ParkedTile
  open_power_mismatches: ParkedTile
}
export interface MyWork { jobs: ParkedTile; dcreqs: ParkedTile; held_imports: ParkedTile }
export interface HomeAdmin { profile_health: ProfileHealth; device_issues: DeviceIssues; workload: ParkedTile }
export interface HomeSummary {
  generated_at: string
  my_work: MyWork
  /** Present for admins only; omitted (not null) for technician and read-only. */
  admin?: HomeAdmin
}

export type SearchGroupKey = 'devices' | 'cabinets' | 'rows' | 'halls'
export interface SearchDeviceItem {
  id: number
  label: string
  hostname: string
  serial: string | null
  status: string
  rack_id: number | null
  rack_name: string | null
  position_u: number | null
}
export interface SearchCabinetItem {
  id: number
  label: string
  name: string
  row_id: number
  row_name: string
  hall_id: number
  hall_name: string
}
/** A row or hall hit. hall_id is not in the committed contract (needed to link a row); compose fills it when it can. */
export interface SearchPlaceItem {
  id: number
  label: string
  name: string
  site_id: number | null
  site_name: string | null
  hall_id?: number | null
}
export interface SearchGroupBase<K extends SearchGroupKey, T> { key: K; count: number; truncated: boolean; items: T[] }
export type DeviceSearchGroup = SearchGroupBase<'devices', SearchDeviceItem>
export type CabinetSearchGroup = SearchGroupBase<'cabinets', SearchCabinetItem>
export type RowSearchGroup = SearchGroupBase<'rows', SearchPlaceItem>
export type HallSearchGroup = SearchGroupBase<'halls', SearchPlaceItem>
export type SearchGroup = DeviceSearchGroup | CabinetSearchGroup | RowSearchGroup | HallSearchGroup
export interface HomeSearch {
  query: string
  generated_at: string
  groups: SearchGroup[]
  parked: ParkedTile[]
}

export interface HomeApi {
  summary(): Promise<HomeSummary>
  search(q: string, limit?: number, signal?: AbortSignal): Promise<HomeSearch>
}

export function emptySearch(query = ''): HomeSearch {
  return {
    query,
    generated_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    groups: [
      { key: 'devices', count: 0, truncated: false, items: [] },
      { key: 'cabinets', count: 0, truncated: false, items: [] },
      { key: 'rows', count: 0, truncated: false, items: [] },
      { key: 'halls', count: 0, truncated: false, items: [] },
    ],
    parked: [PARKED.dcreq_search],
  }
}

export function searchHref(group: SearchGroupKey, item: SearchDeviceItem | SearchCabinetItem | SearchPlaceItem): string | undefined {
  if (group === 'devices') {
    const d = item as SearchDeviceItem
    return d.rack_id != null ? `/cabinets/${d.rack_id}?device=${d.id}` : `/devices?q=${encodeURIComponent(d.hostname)}`
  }
  if (group === 'cabinets') {
    const c = item as SearchCabinetItem
    return c.hall_id ? `/halls/${c.hall_id}/cabinets/${c.id}` : `/cabinets/${c.id}`
  }
  if (group === 'halls') return `/halls/${item.id}`
  const hallId = (item as SearchPlaceItem).hall_id
  return hallId != null ? `/halls/${hallId}/rows/${item.id}` : undefined
}

export function searchSubtitle(group: SearchGroupKey, item: SearchDeviceItem | SearchCabinetItem | SearchPlaceItem): string | undefined {
  if (group === 'devices') {
    const d = item as SearchDeviceItem
    const place = d.rack_id != null ? `${d.rack_name ?? 'Cabinet'} · RU${d.position_u ?? '?'}` : 'No position'
    return [place, d.serial ? `SN ${d.serial}` : null].filter(Boolean).join(' · ')
  }
  if (group === 'cabinets') {
    const c = item as SearchCabinetItem
    return [c.row_name, c.hall_name].filter(Boolean).join(' · ')
  }
  const p = item as SearchPlaceItem
  return p.site_name ?? undefined
}

function clampLimit(limit: number | undefined): number {
  const n = limit ?? SEARCH_DEFAULT_LIMIT
  return Math.min(SEARCH_MAX_LIMIT, Math.max(1, n))
}

export function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong'
}

/** Treat offset-less timestamps as UTC; keep offset-bearing values as given. */
export function parseApiDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const s = iso.trim()
  const hasZone = /[zZ]$/.test(s) || /[+-]\d{2}:?\d{2}$/.test(s)
  const normalised = s.includes('T') ? s : s.replace(' ', 'T')
  const t = Date.parse(hasZone ? normalised : `${normalised}Z`)
  return Number.isNaN(t) ? null : new Date(t)
}

export function daysSince(iso: string | null | undefined, now = Date.now()): number | null {
  const d = parseApiDate(iso)
  return d ? (now - d.getTime()) / 86_400_000 : null
}

export function daysLabel(days: number): string {
  const n = Math.floor(days)
  if (n <= 0) return 'today'
  return n === 1 ? '1 day ago' : `${n} days ago`
}

function cap<T>(items: T[], limit: number): { count: number; truncated: boolean; items: T[] } {
  return { count: items.length, truncated: items.length > limit, items: items.slice(0, limit) }
}

type RawProfile = Record<string, unknown> & { id: number; name: string }

function displayOf(r: RawProfile): string {
  const p = toUiProfile(r as unknown as ProfileListItem)
  return profileDisplayName(p.manufacturer, p.model, p.name)
}

export function composeProfileHealth(rows: RawProfile[], now = Date.now()): ProfileHealth {
  const published = rows.filter((r) => r.status === 'published')
  const drafts = rows.filter((r) => r.status === 'draft')
  const retired = rows.filter((r) => r.status === 'retired')

  const reviewSrc = published.map((r) => {
      const u = toUiProfile(r as unknown as ProfileListItem)
      return { r, name: displayOf(r), issues: u.usableIssues, usable: u.usable }
    }).filter((x) => needsReview({ status: 'published', usable: x.usable }))
  reviewSrc.sort((a, b) => b.issues.length - a.issues.length || a.issues.join().localeCompare(b.issues.join()) || a.r.id - b.r.id)
  const by_issue = {
    rear_image_missing: reviewSrc.filter((x) => x.issues.includes('rear_image_missing')).length,
    orientation_missing: reviewSrc.filter((x) => x.issues.includes('orientation_missing')).length,
  }
  const reviewItems: NeedsReviewItem[] = reviewSrc.map((x) => ({
    id: x.r.id, name: x.name, usable_issue: x.issues[0] ?? null, usable_issues: x.issues,
  }))

  const staleSrc = drafts.map((r) => ({ r, days: daysSince(typeof r.updated_at === 'string' ? r.updated_at : null, now), at: typeof r.updated_at === 'string' ? r.updated_at : null }))
    .filter((x): x is { r: RawProfile; days: number; at: string } => x.at != null && x.days != null && x.days >= STALE_DRAFT_DAYS)
    .sort((a, b) => a.at.localeCompare(b.at) || a.r.id - b.r.id)
  const retiredSrc = retired.map((r) => ({ r, days: daysSince(typeof r.retired_at === 'string' ? r.retired_at : null, now), at: typeof r.retired_at === 'string' ? r.retired_at : null }))
    .filter((x): x is { r: RawProfile; days: number; at: string } => x.at != null && x.days != null && x.days <= RECENTLY_RETIRED_DAYS)
    .sort((a, b) => b.at.localeCompare(a.at) || a.r.id - b.r.id)
  const changedSrc = rows.map((r) => ({ r, at: typeof r.updated_at === 'string' ? r.updated_at : null }))
    .filter((x): x is { r: RawProfile; at: string } => x.at != null)
    .sort((a, b) => b.at.localeCompare(a.at) || a.r.id - b.r.id)

  return {
    key: 'profile_health',
    by_status: { draft: drafts.length, published: published.length, retired: retired.length },
    needs_review: { ...cap(reviewItems, HOME_LIST_LIMIT), by_issue, filter: 'status=published&usable=false' },
    stale_drafts: { ...cap(staleSrc.map((x) => ({ id: x.r.id, name: displayOf(x.r), updated_at: x.at })), HOME_LIST_LIMIT), filter: 'status=draft' },
    recently_retired: { ...cap(retiredSrc.map((x) => ({ id: x.r.id, name: displayOf(x.r), retired_at: x.at })), HOME_LIST_LIMIT), filter: 'status=retired' },
    recently_changed: { ...cap(changedSrc.map((x) => {
      const status: ProfileStatus = x.r.status === 'draft' || x.r.status === 'published' || x.r.status === 'retired' ? x.r.status : 'published'
      return {
        id: x.r.id, name: displayOf(x.r), status,
        updated_at: x.at,
        published_at: typeof x.r.published_at === 'string' ? x.r.published_at : null,
        retired_at: typeof x.r.retired_at === 'string' ? x.r.retired_at : null,
      }
    }), HOME_LIST_LIMIT), count: rows.length, truncated: rows.length > HOME_LIST_LIMIT },
  }
}

export function composeDeviceIssues(items: { id: number; host_name?: string; hostname?: string; status: string; updated_at?: string | null }[], total?: number): DeviceIssues {
  const mapped: UnpositionedDevice[] = items.slice(0, UNPOSITIONED_DEVICE_LIMIT).map((d) => ({
    id: d.id,
    hostname: d.hostname ?? d.host_name ?? `#${d.id}`,
    status: d.status,
    updated_at: d.updated_at ?? '',
  }))
  const count = total ?? items.length
  return {
    key: 'device_issues',
    no_position: { count, truncated: count > UNPOSITIONED_DEVICE_LIMIT, items: mapped, filter: 'status=install&status=active&unplaced=true' },
    needs_power_assignment: PARKED.needs_power_assignment,
    port_conflicts: PARKED.port_conflicts,
    open_power_mismatches: PARKED.open_power_mismatches,
  }
}

async function listProfilesByStatus(status: ProfileStatus): Promise<{ items: RawProfile[]; total: number }> {
  const page = await listPage<RawProfile>('/profiles', { status, limit: 500 })
  return { items: page.items, total: page.total }
}

export async function composeProfileHealthFromApi(now = Date.now()): Promise<ProfileHealth> {
  const [pub, draft, retired] = await Promise.all([
    listProfilesByStatus('published'),
    listProfilesByStatus('draft'),
    listProfilesByStatus('retired'),
  ])
  const health = composeProfileHealth([...pub.items, ...draft.items, ...retired.items], now)
  return { ...health, by_status: { draft: draft.total, published: pub.total, retired: retired.total } }
}

export async function composeDeviceIssuesFromApi(): Promise<DeviceIssues> {
  const res = await send(`/devices?status=install&status=active&unplaced=true&limit=${UNPOSITIONED_DEVICE_LIMIT}`)
  const items = (await res.json()) as Device[]
  const header = res.headers.get('X-Total-Count')
  return composeDeviceIssues(items, header !== null ? Number(header) : items.length)
}

export async function composeSummary(includeAdmin: boolean, now = Date.now()): Promise<HomeSummary> {
  const out: HomeSummary = { generated_at: new Date(now).toISOString().replace(/\.\d{3}Z$/, 'Z'), my_work: parkedMyWork() }
  if (!includeAdmin) return out
  const [p, d] = await Promise.allSettled([composeProfileHealthFromApi(now), composeDeviceIssuesFromApi()])
  if (p.status === 'rejected') throw p.reason
  out.admin = {
    profile_health: p.value,
    device_issues: d.status === 'fulfilled' ? d.value : composeDeviceIssues([]),
    workload: PARKED.workload,
  }
  if (d.status === 'rejected') throw d.reason
  return out
}

function normalise(raw: HomeSummary): HomeSummary {
  return {
    generated_at: raw.generated_at,
    my_work: { ...parkedMyWork(), ...raw.my_work },
    ...(raw.admin ? { admin: raw.admin } : {}),
  }
}

export async function fetchSummary(): Promise<HomeSummary> {
  const res = await send('/home/summary')
  return normalise((await res.json()) as HomeSummary)
}

export async function composeSearch(q: string, limit = SEARCH_DEFAULT_LIMIT): Promise<HomeSearch> {
  const term = q.trim()
  if (term.length < SEARCH_MIN) return emptySearch(term)
  const cap = clampLimit(limit)
  const [devices, cabinets, rows, halls] = await Promise.all([
    listPage<Device>('/devices', { q: term, limit: cap }),
    listPage<Rack>('/racks', { q: term, limit: cap }),
    listPage<Row>('/rows', { q: term, limit: cap }),
    listPage<Hall>('/halls', { q: term, limit: cap }),
  ])
  const iso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
  return {
    query: term,
    generated_at: iso,
    groups: [
      {
        key: 'devices', count: devices.total, truncated: devices.total > cap,
        items: devices.items.slice(0, cap).map((d) => ({
          id: d.id, label: d.host_name, hostname: d.host_name, serial: d.serial_number,
          status: d.status, rack_id: d.rack_id ?? null, rack_name: null, position_u: d.position_u ?? null,
        })),
      },
      {
        key: 'cabinets', count: cabinets.total, truncated: cabinets.total > cap,
        items: cabinets.items.slice(0, cap).map((r) => ({
          id: r.id, label: r.name, name: r.name,
          row_id: r.row_id, row_name: '', hall_id: r.hall_id ?? 0, hall_name: '',
        })),
      },
      {
        key: 'rows', count: rows.total, truncated: rows.total > cap,
        items: rows.items.slice(0, cap).map((r) => ({
          id: r.id, label: r.name, name: r.name, site_id: null, site_name: null, hall_id: r.hall_id,
        })),
      },
      {
        key: 'halls', count: halls.total, truncated: halls.total > cap,
        items: halls.items.slice(0, cap).map((h) => ({
          id: h.id, label: h.name, name: h.name, site_id: h.site_id, site_name: null,
        })),
      },
    ],
    parked: [PARKED.dcreq_search],
  }
}

export async function fetchSearch(q: string, limit = SEARCH_DEFAULT_LIMIT, signal?: AbortSignal): Promise<HomeSearch> {
  const term = q.trim()
  if (term.length < SEARCH_MIN) return emptySearch(term)
  const cap = clampLimit(limit)
  const res = await send(`/home/search?q=${encodeURIComponent(term)}&limit=${cap}`, signal ? { signal } : {})
  return (await res.json()) as HomeSearch
}

export function homeApi(): HomeApi {
  return HOME_API.live
    ? {
        async summary() {
          try { return await fetchSummary() }
          catch (e) {
            if (e instanceof ApiError && (e.status === 404 || e.status === 501)) return composeSummary(true)
            throw e
          }
        },
        async search(q, limit, signal) {
          try { return await fetchSearch(q, limit, signal) }
          catch (e) {
            if (e instanceof ApiError && (e.status === 404 || e.status === 501)) return composeSearch(q, limit)
            throw e
          }
        },
      }
    : {
        summary: () => composeSummary(true),
        search: (q, limit) => composeSearch(q, limit),
      }
}

export const homeKeys = {
  all: ['home'] as const,
  summary: ['home', 'summary'] as const,
  search: (q: string, limit: number) => ['home', 'search', q, limit] as const,
}

export function useHomeSummary() {
  return useQuery({ queryKey: homeKeys.summary, queryFn: () => homeApi().summary(), retry: false })
}
export function useHomeSearch(q: string, enabled: boolean, limit = SEARCH_DEFAULT_LIMIT) {
  const cap = clampLimit(limit)
  return useQuery({
    queryKey: homeKeys.search(q, cap),
    queryFn: ({ signal }) => homeApi().search(q, cap, signal),
    enabled: enabled && q.trim().length >= SEARCH_MIN,
    retry: false,
  })
}
