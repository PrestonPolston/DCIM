// Home-page adapter (docs/design/home.md).
// GET /home/summary is not on 00137ad, so HOME_API.live defaults to false and we
// compose from today's endpoints. The typed shapes match Backend's planned
// contract (feat/home-summary): { generated_at, my_work, admin?, parked }.
import { useQuery } from '@tanstack/react-query'
import { ApiError, listPage, send } from './client'
import { needsReview, toUiProfile, type ProfileListItem, type ProfileStatus } from './profiles'
import type { Device, Hall, Rack, Row } from './types'

export const HOME_API = {
  /** true = GET /home/summary; false = compose from existing endpoints + parked tiles. */
  live: false,
}

export const STALE_DRAFT_DAYS = 14
export const RECENTLY_RETIRED_DAYS = 30
export const HOME_LIST_LIMIT = 5
export const UNPOSITIONED_DEVICE_LIMIT = 10
export const SEARCH_MIN = 2
export const SEARCH_LIMIT = 8

export interface ParkedTile { status: 'not_available'; message: string }

export interface ProfileHealthItem {
  id: number
  name: string
  status: ProfileStatus
  updated_at: string | null
  published_at: string | null
  retired_at: string | null
  manufacturer?: string
  model?: string
  variant?: string | null
  device_count?: number | null
  usable_issues?: string[]
}

export interface ProfileHealth {
  counts: { draft: number; published: number; retired: number }
  needs_review: number
  stale_drafts: number
  recently_retired: number
  recently_changed: ProfileHealthItem[]
  needs_review_items: ProfileHealthItem[]
  stale_draft_items: ProfileHealthItem[]
  recently_retired_items: ProfileHealthItem[]
  /** False when list items have no updated_at / retired_at, so windows can't be applied. */
  dates_available: boolean
}

export interface UnpositionedDevice { id: number; hostname: string; status: string }
export interface DeviceIssues { no_position: { count: number; items: UnpositionedDevice[] } }
export interface HomeAdmin { profile_health: ProfileHealth; device_issues: DeviceIssues }
/** Job / DCREQ / held-import counts are parked; nothing to compute today. */
export type HomeMyWork = Record<string, never>

export interface HomeSummary {
  generated_at: string
  my_work: HomeMyWork
  /** Admins only; omitted for technician and read-only. */
  admin?: HomeAdmin
  parked: Record<string, ParkedTile>
  /** Per-tile errors so one failure doesn't take down the page. */
  errors?: Record<string, string>
}

export const PARKED_MESSAGES = {
  overdue_jobs: 'Needs jobs/DCREQ logic (parked)',
  current_jobs: 'Needs jobs/DCREQ logic (parked)',
  recent_dcreqs: 'Needs jobs/DCREQ logic (parked)',
  held_imports: 'Needs jobs/DCREQ logic (parked)',
  workload: 'Needs jobs/DCREQ logic (parked)',
  power_issues: 'Needs jobs/DCREQ logic (parked)',
  dcreq_search: 'Needs jobs/DCREQ logic (parked)',
} as const

export type ParkedId = keyof typeof PARKED_MESSAGES

export function defaultParked(): Record<string, ParkedTile> {
  return Object.fromEntries(
    (Object.entries(PARKED_MESSAGES) as [ParkedId, string][]).map(([k, message]) => [k, { status: 'not_available' as const, message }]),
  )
}

export type SearchKind = 'device' | 'cabinet' | 'row' | 'hall'
export interface HomeSearchHit { kind: SearchKind; id: number; label: string; href: string; subtitle?: string }
export interface HomeSearchResults {
  devices: HomeSearchHit[]
  cabinets: HomeSearchHit[]
  rows: HomeSearchHit[]
  halls: HomeSearchHit[]
  dcreqs: ParkedTile
}

export interface HomeApi {
  summary(includeAdmin: boolean): Promise<HomeSummary>
  profileHealth(): Promise<ProfileHealth>
  deviceIssues(): Promise<DeviceIssues>
  search(q: string): Promise<HomeSearchResults>
}

export function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong'
}

/** Treat offset-less timestamps as UTC (same rule as other profile dates). */
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

function itemFromProfile(r: Record<string, unknown>): ProfileHealthItem {
  const p = toUiProfile(r as unknown as ProfileListItem)
  const status: ProfileStatus = r.status === 'draft' || r.status === 'published' || r.status === 'retired' ? r.status : 'published'
  return {
    id: p.id,
    name: [p.manufacturer, p.model].filter(Boolean).join(' ') || p.name,
    status,
    updated_at: typeof r.updated_at === 'string' ? r.updated_at : null,
    published_at: typeof r.published_at === 'string' ? r.published_at : null,
    retired_at: typeof r.retired_at === 'string' ? r.retired_at : null,
    manufacturer: p.manufacturer,
    model: p.model,
    variant: p.isDefault ? null : p.name,
    device_count: p.deviceCount,
    usable_issues: p.usableIssues,
  }
}

export function composeProfileHealth(rows: Record<string, unknown>[], now = Date.now()): ProfileHealth {
  const items = rows.map(itemFromProfile)
  const dates_available = rows.some((r) => typeof r.updated_at === 'string' || typeof r.retired_at === 'string')
  const drafts = items.filter((p) => p.status === 'draft')
  const published = items.filter((p) => p.status === 'published')
  const retired = items.filter((p) => p.status === 'retired')
  const reviewItems = items.filter((p) => needsReview({ status: p.status, usable: (p.usable_issues ?? []).length === 0 }))
  const staleItems = dates_available
    ? drafts.filter((p) => {
        const d = daysSince(p.updated_at, now)
        return d != null && d >= STALE_DRAFT_DAYS
      })
    : []
  const recentRetiredItems = dates_available
    ? retired.filter((p) => {
        const d = daysSince(p.retired_at, now)
        return d != null && d <= RECENTLY_RETIRED_DAYS
      })
    : []
  const changed = [...items].filter((p) => p.updated_at).sort((a, b) => {
    const da = parseApiDate(a.updated_at)?.getTime() ?? 0
    const db = parseApiDate(b.updated_at)?.getTime() ?? 0
    return db - da
  })
  const cap = (xs: ProfileHealthItem[]) => xs.slice(0, HOME_LIST_LIMIT)
  return {
    counts: { draft: drafts.length, published: published.length, retired: retired.length },
    needs_review: reviewItems.length,
    stale_drafts: staleItems.length,
    recently_retired: recentRetiredItems.length,
    recently_changed: cap(changed),
    needs_review_items: cap(reviewItems),
    stale_draft_items: cap(staleItems),
    recently_retired_items: cap(recentRetiredItems),
    dates_available,
  }
}

export function composeDeviceIssues(items: { id: number; host_name?: string; hostname?: string; status: string }[], total?: number): DeviceIssues {
  const mapped: UnpositionedDevice[] = items.slice(0, UNPOSITIONED_DEVICE_LIMIT).map((d) => ({
    id: d.id,
    hostname: d.hostname ?? d.host_name ?? `#${d.id}`,
    status: d.status,
  }))
  return { no_position: { count: total ?? items.length, items: mapped } }
}

async function listProfilesByStatus(status: ProfileStatus): Promise<{ items: Record<string, unknown>[]; total: number }> {
  const page = await listPage<Record<string, unknown>>('/profiles', { status, limit: 500 })
  return { items: page.items, total: page.total }
}

export async function composeProfileHealthFromApi(now = Date.now()): Promise<ProfileHealth> {
  const [pub, draft, retired] = await Promise.all([
    listProfilesByStatus('published'),
    listProfilesByStatus('draft'),
    listProfilesByStatus('retired'),
  ])
  const health = composeProfileHealth([...pub.items, ...draft.items, ...retired.items], now)
  return { ...health, counts: { draft: draft.total, published: pub.total, retired: retired.total } }
}

export async function composeDeviceIssuesFromApi(): Promise<DeviceIssues> {
  const res = await send(`/devices?status=install&status=active&unplaced=true&limit=${UNPOSITIONED_DEVICE_LIMIT}`)
  const items = (await res.json()) as Device[]
  const header = res.headers.get('X-Total-Count')
  return composeDeviceIssues(items, header !== null ? Number(header) : items.length)
}

function emptySummary(): HomeSummary {
  return { generated_at: new Date().toISOString(), my_work: {}, parked: defaultParked() }
}

function normaliseSummary(raw: HomeSummary): HomeSummary {
  return {
    generated_at: raw.generated_at,
    my_work: raw.my_work ?? {},
    admin: raw.admin,
    parked: { ...defaultParked(), ...(raw.parked ?? {}) },
    errors: raw.errors,
  }
}

let inflight: { at: number; p: Promise<HomeSummary> } | null = null
async function fetchLiveSummary(): Promise<HomeSummary> {
  const now = Date.now()
  if (!inflight || now - inflight.at > 2_000) {
    inflight = { at: now, p: send('/home/summary').then(async (res) => {
      if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`)
      return normaliseSummary((await res.json()) as HomeSummary)
    }) }
  }
  return inflight.p
}

export async function composeSummary(includeAdmin: boolean, now = Date.now()): Promise<HomeSummary> {
  const out = emptySummary()
  out.generated_at = new Date(now).toISOString()
  if (!includeAdmin) return out
  const [p, d] = await Promise.allSettled([composeProfileHealthFromApi(now), composeDeviceIssuesFromApi()])
  out.admin = { profile_health: p.status === 'fulfilled' ? p.value : composeProfileHealth([]), device_issues: d.status === 'fulfilled' ? d.value : composeDeviceIssues([]) }
  const errors: Record<string, string> = {}
  if (p.status === 'rejected') errors.profile_health = errMessage(p.reason)
  if (d.status === 'rejected') errors.device_issues = errMessage(d.reason)
  if (Object.keys(errors).length) out.errors = errors
  return out
}

function liveApi(): HomeApi {
  return {
    async summary(includeAdmin) {
      try {
        const s = await fetchLiveSummary()
        if (!includeAdmin) return { ...s, admin: undefined }
        return s
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 501)) return composeSummary(includeAdmin)
        throw e
      }
    },
    async profileHealth() {
      try {
        const s = await fetchLiveSummary()
        if (s.errors?.profile_health) throw new Error(s.errors.profile_health)
        if (s.admin?.profile_health) return s.admin.profile_health
      } catch (e) {
        if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 501)) throw e
      }
      return composeProfileHealthFromApi()
    },
    async deviceIssues() {
      try {
        const s = await fetchLiveSummary()
        if (s.errors?.device_issues) throw new Error(s.errors.device_issues)
        if (s.admin?.device_issues) return s.admin.device_issues
      } catch (e) {
        if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 501)) throw e
      }
      return composeDeviceIssuesFromApi()
    },
    async search(q) {
      try {
        const res = await send(`/home/search?q=${encodeURIComponent(q)}`)
        if (res.ok) return (await res.json()) as HomeSearchResults
        if (res.status !== 404 && res.status !== 501) throw new ApiError(res.status, `${res.status} ${res.statusText}`)
      } catch (e) {
        if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 501)) throw e
      }
      return composeSearch(q)
    },
  }
}

export async function composeSearch(q: string): Promise<HomeSearchResults> {
  const term = q.trim()
  if (term.length < SEARCH_MIN) {
    return { devices: [], cabinets: [], rows: [], halls: [], dcreqs: { status: 'not_available', message: PARKED_MESSAGES.dcreq_search } }
  }
  const [devices, cabinets, rows, halls] = await Promise.all([
    listPage<Device>('/devices', { q: term, limit: SEARCH_LIMIT }),
    listPage<Rack>('/racks', { q: term, limit: SEARCH_LIMIT }),
    listPage<Row>('/rows', { q: term, limit: SEARCH_LIMIT }),
    listPage<Hall>('/halls', { q: term, limit: SEARCH_LIMIT }),
  ])
  return {
    devices: devices.items.map((d) => ({
      kind: 'device' as const,
      id: d.id,
      label: d.host_name,
      href: d.rack_id ? `/cabinets/${d.rack_id}?device=${d.id}` : `/devices?q=${encodeURIComponent(d.host_name)}`,
      subtitle: d.serial_number ? `SN ${d.serial_number}` : d.status,
    })),
    cabinets: cabinets.items.map((r) => ({
      kind: 'cabinet' as const,
      id: r.id,
      label: r.name,
      href: r.hall_id ? `/halls/${r.hall_id}/cabinets/${r.id}` : `/cabinets/${r.id}`,
    })),
    rows: rows.items.map((r) => ({
      kind: 'row' as const,
      id: r.id,
      label: r.name,
      href: `/halls/${r.hall_id}/rows/${r.id}`,
    })),
    halls: halls.items.map((h) => ({
      kind: 'hall' as const,
      id: h.id,
      label: h.name,
      href: `/halls/${h.id}`,
    })),
    dcreqs: { status: 'not_available', message: PARKED_MESSAGES.dcreq_search },
  }
}

export function homeApi(): HomeApi {
  return HOME_API.live ? liveApi() : {
    summary: (includeAdmin) => composeSummary(includeAdmin),
    profileHealth: () => composeProfileHealthFromApi(),
    deviceIssues: () => composeDeviceIssuesFromApi(),
    search: (q) => composeSearch(q),
  }
}

export const homeKeys = {
  all: ['home'] as const,
  summary: (includeAdmin: boolean) => ['home', 'summary', includeAdmin] as const,
  profileHealth: ['home', 'profile-health'] as const,
  deviceIssues: ['home', 'device-issues'] as const,
  search: (q: string) => ['home', 'search', q] as const,
}

export function useHomeSummary(includeAdmin: boolean) {
  return useQuery({ queryKey: homeKeys.summary(includeAdmin), queryFn: () => homeApi().summary(includeAdmin), retry: false })
}
export function useProfileHealth(enabled: boolean) {
  return useQuery({ queryKey: homeKeys.profileHealth, queryFn: () => homeApi().profileHealth(), enabled, retry: false })
}
export function useDeviceIssues(enabled: boolean) {
  return useQuery({ queryKey: homeKeys.deviceIssues, queryFn: () => homeApi().deviceIssues(), enabled, retry: false })
}
export function useHomeSearch(q: string, enabled: boolean) {
  return useQuery({ queryKey: homeKeys.search(q), queryFn: () => homeApi().search(q), enabled: enabled && q.trim().length >= SEARCH_MIN, retry: false })
}
