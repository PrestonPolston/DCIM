// Cabinet profiles (admin-setup.md §3–§5; Backend plan docs/api/ADMIN_INPUT_PLAN.md rev 3 §2b/§4).
// The ONE adapter for /cabinet-profiles, matching Backend's built contract (feat/cabinet-profiles
// 43bbb1e: docs/API.md "Cabinet profiles" + openapi.json). live = real endpoints; the in-memory mock
// (cabinetProfiles.mock.ts) mirrors the same contract and is what unit tests use.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, request, send } from './client'
import { apiAssetUrl } from './profiles'
import { createMockCabinetApi } from './cabinetProfiles.mock'

export const CABINET_PROFILE_API = {
  /** true = real endpoints; false = in-memory mock (tests set this; see src/test/setup.ts). */
  live: true,
  /** POST /cabinet-profiles/{id}/unretire (retired → published). */
  unretire: true,
  /** POST/PATCH accept `unit: 'mm'|'in'`. The UI converts itself and always sends mm, so this is unused. */
  unitField: false,
}

export type CabinetProfileStatus = 'draft' | 'published' | 'retired'
export type RackUnitWidth = '19in' | '23in'
export const RACK_UNIT_WIDTHS: [RackUnitWidth, string][] = [['19in', '19 in'], ['23in', '23 in']]
export type DoorType = 'none' | 'perforated' | 'solid' | 'split'
export const DOOR_TYPES: [DoorType, string][] = [['perforated', 'Perforated'], ['solid', 'Solid'], ['split', 'Split'], ['none', 'None']]
/** Rail hole style (API enum). The spec's fixed/adjustable is expressed by rail depth min/max instead. */
export type RailType = 'square_hole' | 'round_hole' | 'threaded'
export const RAIL_TYPES: [RailType, string][] = [['square_hole', 'Square hole'], ['round_hole', 'Round hole'], ['threaded', 'Threaded']]

export interface CabinetImageRef { url: string; thumb_url: string; tex_url?: string }
/** Response shape (all lengths in mm, Plan §4a/§4c). */
export interface CabinetProfile {
  id: number
  manufacturer: string
  model: string
  /** Variant name, default "Standard". */
  name: string
  status: CabinetProfileStatus
  /** Profile version: 1, +1 per clone (not a concurrency counter; that's updated_at). */
  version: number
  supersedes_cabinet_profile_id: number | null
  u_height: number | null
  width_mm: number | null
  depth_mm: number | null
  height_mm: number | null
  rack_unit_width: RackUnitWidth | null
  front_door: DoorType | null
  rear_door: DoorType | null
  rail_type: RailType | null
  rail_depth_min_mm: number | null
  rail_depth_max_mm: number | null
  usable_width_mm: number | null
  usable_depth_mm: number | null
  weight_capacity_kg: number | null
  color_hex: string | null
  notes: string | null
  front_image: CabinetImageRef | null
  rear_image: CabinetImageRef | null
  readiness: { ready: boolean; missing: string[] }
  /** Racks using it (the API returns 0 until cabinets link to profiles); null = older server without it. */
  rack_count: number | null
  /** Actor (email) of the latest change (edit, lifecycle or image). */
  updated_by: string | null
  created_at?: string
  /** Concurrency token: PATCH sends it back as expected_updated_at. */
  updated_at?: string
  created_by: string | null
  published_at: string | null
  published_by: string | null
  retired_at: string | null
  retired_by: string | null
}
type ReadOnly = 'id' | 'status' | 'version' | 'supersedes_cabinet_profile_id' | 'front_image' | 'rear_image' | 'readiness' | 'rack_count' | 'created_at' | 'updated_at' | 'created_by' | 'updated_by' | 'published_at' | 'published_by' | 'retired_at' | 'retired_by'
export type CabinetProfileInput = Partial<Omit<CabinetProfile, ReadOnly>>
export type CabinetProfilePatch = CabinetProfileInput & { expected_updated_at?: string }

/** Publish-required fields in checklist order (Plan §4a "Publish rule"). */
export const PUBLISH_FIELDS = ['manufacturer', 'model', 'name', 'u_height', 'width_mm', 'depth_mm', 'height_mm', 'rack_unit_width'] as const
export type PublishField = (typeof PUBLISH_FIELDS)[number]

const oneOf = <T extends string,>(opts: [T, string][], v: string | null): T | null => (opts.some(([k]) => k === v) ? (v as T) : null)
/** Tolerant mapping of a server row (fields missing in older shapes → null). */
export function toCabinetProfile(r: Record<string, unknown>): CabinetProfile {
  const num = (k: string) => (typeof r[k] === 'number' ? (r[k] as number) : null)
  const str = (k: string) => (typeof r[k] === 'string' && r[k] ? (r[k] as string) : null)
  const img = (k: string) => {
    // URLs are relative to the API root (/cabinet-profile-images/…): route them through API_BASE_URL (the Vite /api proxy).
    const v = r[k] as { url?: unknown; thumb_url?: unknown; tex_url?: unknown } | null | undefined
    if (!v || typeof v.url !== 'string') return null
    const url = apiAssetUrl(v.url)
    return { url, thumb_url: typeof v.thumb_url === 'string' ? apiAssetUrl(v.thumb_url) : url, ...(typeof v.tex_url === 'string' ? { tex_url: apiAssetUrl(v.tex_url) } : {}) }
  }
  const rd = r.readiness as { ready?: unknown; missing?: unknown } | undefined
  const status = r.status === 'published' || r.status === 'retired' ? r.status : 'draft'
  return {
    id: Number(r.id), manufacturer: str('manufacturer') ?? '', model: str('model') ?? '', name: str('name') ?? '',
    status, version: num('version') ?? 1, supersedes_cabinet_profile_id: num('supersedes_cabinet_profile_id'),
    u_height: num('u_height'), width_mm: num('width_mm'), depth_mm: num('depth_mm'), height_mm: num('height_mm'),
    rack_unit_width: r.rack_unit_width === '19in' || r.rack_unit_width === '23in' ? r.rack_unit_width : null,
    front_door: oneOf(DOOR_TYPES, str('front_door')), rear_door: oneOf(DOOR_TYPES, str('rear_door')),
    rail_type: oneOf(RAIL_TYPES, str('rail_type')), rail_depth_min_mm: num('rail_depth_min_mm'), rail_depth_max_mm: num('rail_depth_max_mm'),
    usable_width_mm: num('usable_width_mm'), usable_depth_mm: num('usable_depth_mm'), weight_capacity_kg: num('weight_capacity_kg'),
    color_hex: str('color_hex'), notes: str('notes'), front_image: img('front_image'), rear_image: img('rear_image'),
    readiness: { ready: !!rd?.ready, missing: Array.isArray(rd?.missing) ? (rd!.missing as string[]) : [] },
    rack_count: num('rack_count'),
    created_at: str('created_at') ?? undefined, updated_at: str('updated_at') ?? undefined, created_by: str('created_by'), updated_by: str('updated_by'),
    published_at: str('published_at'), published_by: str('published_by'), retired_at: str('retired_at'), retired_by: str('retired_by'),
  }
}

/** GET /cabinet-profiles/{id}/history entry (admin only): before/after hold only the changed fields. */
export interface CabinetHistoryEvent {
  id: number
  occurred_at: string
  /** cabinet_profile.create|update|delete|publish|retire|unretire|clone|image.put|image.delete */
  action: string
  actor_email: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}
export interface Paged<T> { items: T[]; total: number }

export interface CabinetProfileApi {
  history(id: number, p?: { limit?: number; offset?: number }): Promise<Paged<CabinetHistoryEvent>>
  /** Every matching profile: pages through X-Total-Count. */
  list(p?: { status?: CabinetProfileStatus | 'all'; q?: string }): Promise<CabinetProfile[]>
  get(id: number): Promise<CabinetProfile>
  create(body: CabinetProfileInput): Promise<CabinetProfile>
  update(id: number, body: CabinetProfilePatch): Promise<CabinetProfile>
  remove(id: number): Promise<void>
  publish(id: number): Promise<CabinetProfile>
  retire(id: number): Promise<CabinetProfile>
  unretire(id: number): Promise<CabinetProfile>
  /** New draft; without a name the server picks "<name> (copy)", "(copy 2)", … */
  clone(id: number, name?: string): Promise<CabinetProfile>
  uploadImage(id: number, face: 'front' | 'rear', file: Blob): Promise<CabinetProfile>
}

const json = (b: unknown) => JSON.stringify(b)
/** Page size for walking the list (the API allows 1–500, default 50). */
export const PAGE = 200
/** GET a paginated list; total from X-Total-Count (falls back to the item count). */
async function paged<T>(path: string): Promise<Paged<T>> {
  const res = await send(path)
  const items = (await res.json()) as T[]
  const n = Number(res.headers.get('X-Total-Count'))
  return { items, total: Number.isFinite(n) && res.headers.has('X-Total-Count') ? n : items.length }
}
const liveApi: CabinetProfileApi = {
  list: async (p = {}) => {
    const out: CabinetProfile[] = []
    for (;;) {
      const s = new URLSearchParams({ limit: String(PAGE), offset: String(out.length) })
      if (p.status && p.status !== 'all') s.set('status', p.status)
      if (p.q) s.set('q', p.q)
      const { items, total } = await paged<Record<string, unknown>>(`/cabinet-profiles?${s}`)
      out.push(...items.map(toCabinetProfile))
      if (!items.length || out.length >= total) return out
    }
  },
  history: async (id, p = {}) => {
    const s = new URLSearchParams({ limit: String(p.limit ?? 50), offset: String(p.offset ?? 0) })
    return paged<CabinetHistoryEvent>(`/cabinet-profiles/${id}/history?${s}`)
  },
  get: async (id) => toCabinetProfile(await request(`/cabinet-profiles/${id}`)),
  create: async (b) => toCabinetProfile(await request('/cabinet-profiles', { method: 'POST', body: json(b) })),
  update: async (id, b) => toCabinetProfile(await request(`/cabinet-profiles/${id}`, { method: 'PATCH', body: json(b) })),
  remove: (id) => request<void>(`/cabinet-profiles/${id}`, { method: 'DELETE' }),
  publish: async (id) => toCabinetProfile(await request(`/cabinet-profiles/${id}/publish`, { method: 'POST' })),
  retire: async (id) => toCabinetProfile(await request(`/cabinet-profiles/${id}/retire`, { method: 'POST' })),
  unretire: async (id) => toCabinetProfile(await request(`/cabinet-profiles/${id}/unretire`, { method: 'POST' })),
  clone: async (id, name) => toCabinetProfile(await request(`/cabinet-profiles/${id}/clone`, { method: 'POST', body: json(name ? { name } : {}) })),
  uploadImage: async (id, face, file) => {
    await request(`/cabinet-profiles/${id}/images/${face}`, { method: 'PUT', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } })
    return toCabinetProfile(await request(`/cabinet-profiles/${id}`))
  },
}

let mock: CabinetProfileApi | null = null
/** The mock instance (tests reset it with resetCabinetMock). */
export function cabinetMock() { return (mock ??= createMockCabinetApi()) }
export function resetCabinetMock(seed?: Parameters<typeof createMockCabinetApi>[0]) { mock = createMockCabinetApi(seed) }
export const cabinetApi = (): CabinetProfileApi => (CABINET_PROFILE_API.live ? liveApi : cabinetMock())

// ---- hooks -------------------------------------------------------------------
export const cabinetKeys = { all: ['cabinet-profiles'] as const, list: (p: object) => ['cabinet-profiles', 'list', p] as const, one: (id: number) => ['cabinet-profiles', 'one', id] as const }

export function useCabinetProfiles(p: { status?: CabinetProfileStatus | 'all'; q?: string } = {}) {
  return useQuery({ queryKey: cabinetKeys.list(p), queryFn: () => cabinetApi().list(p) })
}
/** Admin only (403 for other roles): callers pass enabled=false for technicians. */
export function useCabinetHistory(id: number | null, enabled = true, limit = 50) {
  return useQuery({ queryKey: [...cabinetKeys.one(id ?? -1), 'history', limit], queryFn: () => cabinetApi().history(id!, { limit }), enabled: enabled && id != null, retry: false })
}
export function useCabinetProfile(id: number | null) {
  return useQuery({ queryKey: cabinetKeys.one(id ?? -1), queryFn: () => cabinetApi().get(id!), enabled: id != null })
}
export function useCabinetActions() {
  const qc = useQueryClient()
  const done = <T,>(r: T) => { void qc.invalidateQueries({ queryKey: cabinetKeys.all }); return r }
  const m = useMutation({ mutationFn: (f: () => Promise<unknown>) => f() })
  const run = <T,>(f: () => Promise<T>) => m.mutateAsync(f).then((r) => done(r as T))
  const api = cabinetApi()
  return {
    busy: m.isPending,
    create: (b: CabinetProfileInput) => run(() => api.create(b)),
    update: (id: number, b: CabinetProfilePatch) => run(() => api.update(id, b)),
    remove: (id: number) => m.mutateAsync(() => api.remove(id)).then(() => { qc.removeQueries({ queryKey: cabinetKeys.one(id) }); return done(undefined) }),
    publish: (id: number) => run(() => api.publish(id)),
    retire: (id: number) => run(() => api.retire(id)),
    unretire: (id: number) => run(() => api.unretire(id)),
    clone: (id: number) => run(() => api.clone(id)),
    uploadImage: (id: number, face: 'front' | 'rear', file: Blob) => run(() => api.uploadImage(id, face, file)),
  }
}

/** Structured error detail of a cabinet-profile call. */
export function cabinetError(e: unknown): { status: number; code: string | null; message: string; detail: Record<string, unknown> } {
  if (e instanceof ApiError) {
    const d = ((e.detail as { detail?: unknown } | undefined)?.detail ?? {}) as Record<string, unknown>
    return { status: e.status, code: e.code, message: e.message, detail: typeof d === 'object' && d ? d : {} }
  }
  return { status: 0, code: null, message: e instanceof Error ? e.message : String(e), detail: {} }
}
