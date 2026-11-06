// THE profile adapter: every API profile field name is read here and nowhere else
// (docs/design/profiles.md; field names per docs/db, not all in the API yet).
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL, deviceTypesApi, listPage, request } from './client'
import type { DeviceProfile, DeviceType } from './types'

export interface UiFrontImage { url: string; thumbUrl: string }

/**
 * Image metadata {url, thumb_url} | null: profiles expose `front_image` (GET /profiles),
 * devices / elevation / row items `effective_front_image` (not landed yet).
 * The deprecated flat `front_image_url` alias is intentionally ignored.
 */
/** The API returns image URLs relative to its own root (`/profile-images/…`); route them through API_BASE_URL. */
export function apiAssetUrl(u: string): string {
  if (!u.startsWith('/') || u.startsWith('//')) return u
  if (API_BASE_URL && (u === API_BASE_URL || u.startsWith(`${API_BASE_URL}/`))) return u
  return `${API_BASE_URL}${u}`
}

/** tex_url: 1024 px WebP for 3D textures (762e01b); the original URL until a DB is backfilled. */
export interface ImageRef { url: string; thumb_url: string; tex_url?: string; width_px?: number; height_px?: number; etag?: string }

/** ProfileImageRef {url, thumb_url, width_px, height_px, etag} (HEAD 46f796d); extra fields optional for older servers. */
function imageRefOf(obj: unknown): ImageRef | null {
  const r = obj as { url?: unknown; thumb_url?: unknown; tex_url?: unknown; width_px?: unknown; height_px?: unknown; etag?: unknown } | null | undefined
  if (!r || typeof r.url !== 'string') return null
  const url = apiAssetUrl(r.url)
  const out: ImageRef = { url, thumb_url: typeof r.thumb_url === 'string' ? apiAssetUrl(r.thumb_url) : url }
  if (typeof r.tex_url === 'string') out.tex_url = apiAssetUrl(r.tex_url)
  if (typeof r.width_px === 'number') out.width_px = r.width_px
  if (typeof r.height_px === 'number') out.height_px = r.height_px
  if (typeof r.etag === 'string') out.etag = r.etag
  return out
}

export function frontImageOf(x: unknown): ImageRef | null {
  const o = (x ?? {}) as Record<string, unknown>
  return imageRefOf(o.effective_front_image ?? o.front_image)
}

/** effective_rear_image (devices/elevation/row items) or rear_image (profiles). */
export function rearImageOf(x: unknown): ImageRef | null {
  const o = (x ?? {}) as Record<string, unknown>
  return imageRefOf(o.effective_rear_image ?? o.rear_image)
}

// ---------------------------------------------------------------------------
// Profile model for the UI (profiles.md §1). Mapping from API rows happens only here.

/**
 * Which planned profile endpoints exist in apps/api/openapi.json (checked 2026-10-24).
 * Flip a flag when Backend ships it; UI shows "not available yet" while false.
 */
export const PROFILE_API = {
  /** GET /profiles?status=&q=&manufacturer=&asset_type=&device_type_id=&in_use= (72fee98). */
  flatList: true,
  /** status draft/published/retired on GET /profiles (server-derived interim status, 72fee98). */
  lifecycle: true,
  /** POST /profiles/{id}/publish (admin), /retire (admin) */
  publish: true,
  /** PUT /device-types/{t}/profiles/{p}/images/{face}, raw body (admin, technician) */
  images: true,
  /** POST /profiles/{id}/clone (admin); /adopt is not in the UI yet */
  versions: true,
  /** device_count on GET /profiles */
  deviceCount: true,
  /** usable / usable_issue / usable_issues + ?usable= (5238001). Older servers: derived client-side. */
  usable: true,
  /**
   * Profile `orientation` (power_front | port_front | null; required to publish a switch; bd5306a / D58):
   * PATCH-able, ?orientation= on GET /profiles, read-only on devices/elevation/row items,
   * POST /profiles/{id}/clone {name?, swap_faces?}.
   */
  orientation: true,
} as const

export type Orientation = 'power_front' | 'port_front'
export const ORIENTATIONS: [Orientation, string][] = [['power_front', 'Power front'], ['port_front', 'Port front']]
export const orientationOf = (v: unknown): Orientation | null => (v === 'power_front' || v === 'port_front' ? v : null)

/** usable_issues → short review label (D54 / profile_not_usable). */
export function issueLabel(issue: string): string {
  if (issue === 'rear_image_missing') return 'Needs rear image'
  if (issue === 'front_image_missing') return 'Needs front image'
  if (issue === 'orientation_missing') return 'Needs orientation'
  if (issue === 'profile_draft') return 'Draft'
  if (issue === 'profile_retired') return 'Retired'
  return `Needs ${issue.replace(/_missing$/, '').replace(/_/g, ' ')}`
}

/**
 * The ONE place usability is read. API fields when present (HEAD 5238001); otherwise derived:
 * draft/retired, published without a rear image, switch with orientation explicitly null.
 */
export function usabilityOf(r: Record<string, unknown>): { usable: boolean; issues: string[] } {
  if (typeof r.usable === 'boolean') {
    const issues = Array.isArray(r.usable_issues) ? (r.usable_issues as string[]) : typeof r.usable_issue === 'string' ? [r.usable_issue] : []
    return { usable: r.usable, issues: r.usable ? [] : issues }
  }
  const issues: string[] = []
  if (r.status === 'draft') issues.push('profile_draft')
  if (r.status === 'retired') issues.push('profile_retired')
  if (r.status === 'published' || r.status == null) {
    if ('rear_image' in r && !rearImageOf(r)) issues.push('rear_image_missing')
    const asset = r.effective_asset_type ?? r.asset_type
    if (asset === 'switch' && 'orientation' in r && r.orientation == null) issues.push('orientation_missing')
  }
  return { usable: issues.length === 0, issues }
}
/** Published but blocked for new use (rear/orientation missing): the "Needs review" state. */
export const needsReview = (p: { status: ProfileStatus | null; usable: boolean }) => (p.status === 'published' || p.status == null) && !p.usable

export type ProfileStatus = 'draft' | 'published' | 'retired'
/** asset_type vocabulary (profiles.md §1 / D26); NULL = unknown. */
/** asset_type vocabulary (D34 + p1_20 cable_manager, the 11th value; in openapi since 7870638); NULL = unknown. */
export const ASSET_TYPES = ['server', 'switch', 'patch_panel', 'pdu', 'router', 'firewall', 'storage', 'blank', 'shelf', 'cable_manager', 'other'] as const
export const ASSET_LABEL: Record<string, string> = {
  server: 'Server', switch: 'Switch', patch_panel: 'Patch panel', pdu: 'PDU', router: 'Router', firewall: 'Firewall',
  storage: 'Storage', blank: 'Blank', shelf: 'Shelf', cable_manager: 'Cable manager', other: 'Other', unknown: 'No asset type',
}
export const MOUNTINGS = [['rack_19in', '19" rack'], ['rack_23in', '23" rack'], ['zero_u', '0U'], ['shelf', 'Shelf']] as const

export interface UiProfile {
  id: number
  deviceTypeId: number
  manufacturer: string
  model: string
  /** Profile name; shown as the variant unless it's the type's default. */
  name: string
  isDefault: boolean
  uHeight: number
  isFullDepth: boolean
  widthMm: number | null
  heightMm: number | null
  depthMm: number | null
  mounting: string | null
  powerType: string | null
  assetType: string | null
  colorHex: string | null
  /** null = the API has no lifecycle yet (PROFILE_API.lifecycle). */
  status: ProfileStatus | null
  version: number | null
  /** device_count from GET /profiles (null when unknown). */
  deviceCount: number | null
  frontImage: { url: string; thumb_url: string } | null
  rearImage: ImageRef | null
  usable: boolean
  usableIssues: string[]
  orientation: Orientation | null
  /** Server readiness missing[] when provided; null = unknown. */
  missing: string[] | null
}

const numOrNull = (v: unknown) => (typeof v === 'number' ? v : null)
const strOrNull = (v: unknown) => (typeof v === 'string' && v ? v : null)

/** Maps a GET /profiles ProfileListItem (or a per-type DeviceProfile plus its type). */
export function toUiProfile(p: DeviceProfile | ProfileListItem, t?: DeviceType): UiProfile {
  const r = p as unknown as Record<string, unknown>
  const status = r.status === 'draft' || r.status === 'published' || r.status === 'retired' ? r.status : null
  const readiness = r.readiness as { missing?: unknown } | undefined
  return {
    id: p.id,
    deviceTypeId: p.device_type_id,
    manufacturer: strOrNull(r.manufacturer) ?? t?.manufacturer ?? '',
    model: strOrNull(r.model) ?? t?.name ?? '',
    name: p.name,
    isDefault: !!p.is_default,
    uHeight: p.u_height ?? t?.u_height ?? 1,
    isFullDepth: p.is_full_depth ?? t?.is_full_depth ?? true,
    widthMm: numOrNull(r.width_mm), heightMm: numOrNull(r.height_mm), depthMm: numOrNull(r.depth_mm),
    mounting: strOrNull(r.mounting),
    powerType: strOrNull(r.power_type),
    assetType: strOrNull(r.effective_asset_type) ?? strOrNull(r.asset_type) ?? strOrNull((t as unknown as Record<string, unknown> | undefined)?.asset_type),
    colorHex: strOrNull(r.color_hex),
    status,
    version: numOrNull(r.version),
    deviceCount: numOrNull(r.device_count),
    frontImage: frontImageOf(r),
    rearImage: rearImageOf(r),
    ...((u) => ({ usable: u.usable, usableIssues: u.issues }))(usabilityOf({ ...r, status })),
    orientation: orientationOf(r.orientation),
    missing: Array.isArray(readiness?.missing) ? (readiness!.missing as string[]) : null,
  }
}

/** Placeable from the palette: published (or lifecycle unknown in today's API) and not legacy/retired. */
export const isPlaceable = (p: UiProfile) => (p.status == null || p.status === 'published') && p.usable
export const profileTitle = (p: UiProfile) => `${p.manufacturer} ${p.model}`.trim()
export const variantOf = (p: UiProfile) => (p.isDefault ? null : p.name)
export function specLine(p: UiProfile): string {
  const mount = MOUNTINGS.find(([v]) => v === p.mounting)?.[1]
  return [`${p.uHeight}U`, p.isFullDepth ? 'Full' : 'Half', mount].filter(Boolean).join(' · ')
}

// ---- drag payload: dragged items carry a profile, not a type ----------------
export const PROFILE_MIME = 'application/x-dcim-profile'
export interface PlacingProfile { kind: 'profile'; profileId: number; deviceTypeId: number; uHeight: number; isFullDepth: boolean; label: string }
export const placingOf = (p: UiProfile): PlacingProfile => ({
  kind: 'profile', profileId: p.id, deviceTypeId: p.deviceTypeId, uHeight: p.uHeight, isFullDepth: p.isFullDepth,
  label: [profileTitle(p), variantOf(p)].filter(Boolean).join(' · '),
})
export function parsePlacing(s: string | null | undefined): PlacingProfile | null {
  try {
    const v = JSON.parse(s ?? '') as PlacingProfile
    return v && v.kind === 'profile' && typeof v.profileId === 'number' ? v : null
  } catch {
    return null
  }
}
/** Device body fields for a placement from a profile (server derives/validates the type). */
export const placementBody = (p: PlacingProfile) => ({ profile_id: p.profileId, device_type_id: p.deviceTypeId })

// ---- list hook (palette, picker, Profiles screen) ---------------------------
export interface ProfileFilters { q?: string; assetType?: string; u?: '1' | '2' | '4+'; depth?: 'full' | 'half'; status?: ProfileStatus | 'all' }

export function matches(p: UiProfile, f: ProfileFilters): boolean {
  const q = f.q?.trim().toLowerCase()
  if (q && ![p.manufacturer, p.model, p.name].some((x) => x.toLowerCase().includes(q))) return false
  if (f.assetType && (p.assetType ?? 'unknown') !== f.assetType) return false
  if (f.u === '1' && p.uHeight !== 1) return false
  if (f.u === '2' && p.uHeight !== 2) return false
  if (f.u === '4+' && p.uHeight < 4) return false
  if (f.depth && p.isFullDepth !== (f.depth === 'full')) return false
  const st = f.status ?? 'published'
  if (st === 'published' && !isPlaceable(p)) return false
  if ((st === 'draft' || st === 'retired') && p.status !== st) return false
  return true
}

export interface ProfileListItem {
  id: number; name: string; device_type_id: number; manufacturer: string; model: string
  u_height: number; is_full_depth: boolean; is_default: boolean
  width_mm?: number | null; height_mm?: number | null; depth_mm?: number | null; power_type?: string | null
  asset_type?: string | null; effective_asset_type?: string | null; color_hex?: string | null
  status?: ProfileStatus; device_count?: number
  front_image?: { url: string; thumb_url: string } | null
}
const MAX = 500

/**
 * GET /profiles (72fee98) with server-side status / q / asset_type; U-height and depth
 * chips are filtered locally. Unknown asset type is filtered locally too.
 */
export function useProfiles(filters: ProfileFilters = {}) {
  const status = filters.status ?? 'published'
  const params = {
    status: status === 'all' ? undefined : status,
    q: filters.q?.trim() || undefined,
    asset_type: filters.assetType && filters.assetType !== 'unknown' ? filters.assetType : undefined,
    limit: MAX,
  }
  const q = useQuery({ queryKey: profileKeys.list(params), queryFn: () => listProfiles(params) })
  const drafts = useQuery({ queryKey: profileKeys.list({ status: 'draft', limit: 1 }), queryFn: () => listProfiles({ status: 'draft', limit: 1 }) })
  const types = useQuery({ queryKey: ['device-types', 'all'], queryFn: () => deviceTypesApi.list({ limit: MAX }) })
  const all = (q.data?.items ?? []).map((p) => toUiProfile(p))
  const items = all.filter((p) => matches(p, { ...filters, status: 'all' }))
  /** Published but not usable (Needs review): shown disabled in pickers with the reason. */
  const flagged = all.filter((p) => needsReview(p) && matches(p, { ...filters, status: 'all' }))
  return { items, all, flagged, total: q.data?.total ?? 0, drafts: drafts.data?.total ?? 0, isPending: q.isPending, error: q.error, types: types.data?.items ?? [] }
}

export const profileKeys = { all: ['profiles'] as const, list: (p: object) => ['profiles', 'list', p] as const }
export function listProfiles(params: Record<string, string | number | boolean | undefined>) {
  return listPage<ProfileListItem>('/profiles', params)
}

// ---- Add profile: local checklist, image rules, Save draft -----------------
export interface ProfileForm {
  manufacturer: string; model: string; assetType: string; name: string
  uHeight: string; mounting: string; fullDepth: boolean
  widthMm: string; heightMm: string; depthMm: string; powerType: string
  frontImage: File | null; rearImage: File | null
  /** Switches only; sent/checked only when PROFILE_API.orientation. */
  orientation: Orientation | ''
}
export const emptyProfileForm = (patch: Partial<ProfileForm> = {}): ProfileForm => ({
  manufacturer: '', model: '', assetType: '', name: 'Default', uHeight: '1', mounting: 'rack_19in', fullDepth: true,
  widthMm: '', heightMm: '', depthMm: '', powerType: '', frontImage: null, rearImage: null, orientation: '', ...patch,
})

/** Publish checklist (profiles.md §2). Local guide only: the server's missing[] is authoritative. */
export const CHECKLIST: { key: string; label: string; ok: (f: ProfileForm) => boolean }[] = [
  { key: 'model', label: 'Manufacturer and model', ok: (f) => !!f.manufacturer.trim() && !!f.model.trim() },
  { key: 'name', label: 'Profile name', ok: (f) => !!f.name.trim() },
  { key: 'asset_type', label: 'Asset type', ok: (f) => !!f.assetType },
  { key: 'u_height', label: 'U height', ok: (f) => { const u = Number(f.uHeight); return Number.isInteger(u) && (u >= 1 ? u <= 100 : u === 0 && f.mounting === 'zero_u') } },
  { key: 'dimensions', label: 'Width / Height / Depth (mm)', ok: (f) => [f.widthMm, f.heightMm, f.depthMm].every((v) => Number(v) > 0) },
  { key: 'is_full_depth', label: 'Full or half depth', ok: () => true },
  { key: 'mounting', label: 'Mounting', ok: (f) => !!f.mounting },
  { key: 'front_image', label: 'Front image', ok: (f) => !!f.frontImage },
  { key: 'rear_image', label: 'Rear image', ok: (f) => !!f.rearImage },
  { key: 'power_type', label: 'Power type (AC/DC)', ok: (f) => !!f.powerType },
  { key: 'orientation', label: 'Orientation (Power front / Port front)', ok: (f) => f.assetType !== 'switch' || !!f.orientation },
]
/** Checklist rows that apply to this form (orientation: switches only, once the API has the field). */
const applies = (key: string, f: ProfileForm) => key !== 'orientation' || (PROFILE_API.orientation && f.assetType === 'switch')
/** Server missing[] field names → checklist keys. */
const MISSING_KEY: Record<string, string> = {
  device_type_id: 'model', name: 'name', asset_type: 'asset_type', u_height: 'u_height', width_mm: 'dimensions', height_mm: 'dimensions', depth_mm: 'dimensions',
  is_full_depth: 'is_full_depth', mounting: 'mounting', front_image: 'front_image', rear_image: 'rear_image', power_type: 'power_type', orientation: 'orientation',
}
export function checklist(f: ProfileForm, serverMissing: string[] | null = null) {
  const bad = serverMissing ? new Set(serverMissing.map((m) => MISSING_KEY[m] ?? m)) : null
  return CHECKLIST.filter((c) => applies(c.key, f)).map((c) => ({ key: c.key, label: c.label, ok: bad ? !bad.has(c.key) && c.ok(f) : c.ok(f) }))
}
export const canSaveDraft = (f: ProfileForm) => !!f.manufacturer.trim() && !!f.model.trim() && !!f.name.trim()
export function heightWarning(f: ProfileForm): string | null {
  const u = Number(f.uHeight), h = Number(f.heightMm)
  if (!(u >= 1) || !(h > 0)) return null
  const expected = u * 44.45
  return Math.abs(h - expected) / expected > 0.1 ? `Height ${h} mm is more than 10% off ${u}U (${expected.toFixed(1)} mm).` : null
}

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const IMAGE_MAX_BYTES = 2 * 1024 * 1024
export const IMAGE_MAX_PX = 4096
/** D28 client pre-check. Pass pixel size when known (decoded); the server re-checks. */
export const HEIC_TEXT = "HEIC isn't supported yet. Export as JPEG or PNG."
export const isHeic = (f: { name: string; type: string }) => /heic|heif/i.test(f.type) || /\.(heic|heif)$/i.test(f.name)
export function imageProblem(file: { name: string; type: string; size: number }, px?: { w: number; h: number }): string | null {
  if (isHeic(file)) return HEIC_TEXT
  if (file.type === 'image/svg+xml' || /\.svg$/i.test(file.name)) return "SVG isn't supported. Export a PNG."
  if (!IMAGE_TYPES.includes(file.type)) return 'Use a PNG, JPEG or WebP image.'
  if (file.size > IMAGE_MAX_BYTES) return 'The image is larger than 2 MiB.'
  if (px && (px.w > IMAGE_MAX_PX || px.h > IMAGE_MAX_PX)) return `The image is larger than ${IMAGE_MAX_PX} × ${IMAGE_MAX_PX} px.`
  return null
}

const n = (v: string) => (v.trim() === '' ? null : Number(v))
/**
 * Save draft: find or POST /device-types for the model (with asset_type), then
 * POST /device-types/{id}/profiles (a new profile is a draft server-side), then
 * PUT the chosen front/rear images as raw bodies.
 */
export function useSaveProfileDraft() {
  const qc = useQueryClient()
  return async (f: ProfileForm, types: DeviceType[]): Promise<DeviceProfile> => {
    const same = (t: DeviceType) => t.manufacturer.trim().toLowerCase() === f.manufacturer.trim().toLowerCase() && t.name.trim().toLowerCase() === f.model.trim().toLowerCase()
    let type = types.find(same)
    if (!type) {
      type = await request<DeviceType>('/device-types', {
        method: 'POST',
        body: JSON.stringify({ manufacturer: f.manufacturer.trim(), name: f.model.trim(), u_height: Number(f.uHeight) || 1, is_full_depth: f.fullDepth, asset_type: f.assetType || null }),
      })
    }
    const body = {
      name: f.name.trim(), is_full_depth: f.fullDepth, mounting: f.mounting || null,
      width_mm: n(f.widthMm), height_mm: n(f.heightMm), depth_mm: n(f.depthMm), power_type: f.powerType || null,
      ...(PROFILE_API.orientation && f.assetType === 'switch' && f.orientation ? { orientation: f.orientation } : {}),
    }
    const created = await request<DeviceProfile>(`/device-types/${type.id}/profiles`, { method: 'POST', body: JSON.stringify(body) })
    if (f.frontImage) await uploadProfileImage(type.id, created.id, 'front', f.frontImage)
    if (f.rearImage) await uploadProfileImage(type.id, created.id, 'rear', f.rearImage)
    await Promise.all([qc.invalidateQueries({ queryKey: ['device-types'] }), qc.invalidateQueries({ queryKey: profileKeys.all })])
    return created
  }
}

/** Duplicate check while typing (case-insensitive manufacturer + model). */
export function findDuplicate(f: ProfileForm, all: UiProfile[]): UiProfile[] {
  const m = f.manufacturer.trim().toLowerCase(), mo = f.model.trim().toLowerCase()
  if (!m || !mo) return []
  return all.filter((p) => p.manufacturer.toLowerCase() === m && p.model.toLowerCase() === mo)
}

// ---- lifecycle + images (docs/API.md "Profile lifecycle", PROFILE_IMAGES) ----
/** PUT raw image bytes (no multipart); Content-Type is the file's type (png/jpeg/webp). */
export function uploadProfileImage(typeId: number, profileId: number, face: 'front' | 'rear', file: Blob) {
  return request<unknown>(`/device-types/${typeId}/profiles/${profileId}/images/${face}`, {
    method: 'PUT', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' },
  })
}

/** 422 profile_not_ready → the server's missing[] (else null). */
export function missingFromError(e: unknown): string[] | null {
  const d = (e as { detail?: { detail?: { code?: string; missing?: unknown } } } | null)?.detail?.detail
  return d && Array.isArray(d.missing) ? (d.missing as string[]) : null
}

/** Readable labels for server missing[] fields. */
export const MISSING_LABEL: Record<string, string> = {
  name: 'name', asset_type: 'asset type', u_height: 'U height', width_mm: 'width', height_mm: 'height', depth_mm: 'depth',
  mounting: 'mounting', power_type: 'power type (AC/DC)', front_image: 'front image', rear_image: 'rear image', orientation: 'orientation (Power front / Port front)', device_type_id: 'model',
}
export const missingText = (m: string[]) => m.map((x) => MISSING_LABEL[x] ?? x.replace(/_/g, ' ')).join(', ')

export function useProfileActions() {
  const qc = useQueryClient()
  const done = () => Promise.all([qc.invalidateQueries({ queryKey: profileKeys.all }), qc.invalidateQueries({ queryKey: ['device-types'] })])
  const post = async (path: string, body?: unknown) => { const r = await request<DeviceProfile>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }); await done(); return r }
  return {
    publish: (id: number) => post(`/profiles/${id}/publish`),
    retire: (id: number) => post(`/profiles/${id}/retire`),
    newVersion: (id: number) => post(`/profiles/${id}/clone`, {}),
    /** PATCH orientation (a NULL one may be filled even on a published, in-use profile). */
    setOrientation: async (p: UiProfile, orientation: Orientation) => {
      await request<DeviceProfile>(`/device-types/${p.deviceTypeId}/profiles/${p.id}`, { method: 'PATCH', body: JSON.stringify({ orientation }) }); await done()
    },
    /** "Add orientation variant": clone with swap_faces (server flips orientation and swaps the images). */
    orientationVariant: (id: number, name: string) => post(`/profiles/${id}/clone`, { name: name.trim() || undefined, swap_faces: true }),
    remove: async (p: UiProfile) => { await request<void>(`/device-types/${p.deviceTypeId}/profiles/${p.id}`, { method: 'DELETE' }); await done() },
    upload: async (p: UiProfile, face: 'front' | 'rear', file: File) => { await uploadProfileImage(p.deviceTypeId, p.id, face, file); await done() },
  }
}

export const otherOrientation = (o: Orientation): Orientation => (o === 'power_front' ? 'port_front' : 'power_front')
/** Designer auto name: `{model} (Power Front|Port Front)`. */
export const orientationName = (model: string, o: Orientation) => `${model.trim()} (${o === 'power_front' ? 'Power Front' : 'Port Front'})`
