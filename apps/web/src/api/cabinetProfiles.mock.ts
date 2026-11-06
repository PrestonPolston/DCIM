// In-memory /cabinet-profiles used when CABINET_PROFILE_API.live is false (unit tests).
// It mirrors Backend's built contract (feat/cabinet-profiles 43bbb1e, docs/API.md "Cabinet profiles"):
// codes cabinet_profile_incomplete, invalid_status_transition, invalid_dimension, cabinet_profile_name_taken,
// cabinet_profile_retired, cabinet_profile_in_use (superseded), version_conflict (expected_updated_at).
// Errors take the real shape: ApiError(status, msg, {detail: {code, message, …}}).
import { ApiError } from './client'
import type { CabinetHistoryEvent, CabinetProfile, CabinetProfileApi, CabinetProfileInput, PublishField } from './cabinetProfiles'

export const PUBLISH_LABELS: Record<PublishField, string> = {
  manufacturer: 'Manufacturer', model: 'Model', name: 'Variant name', u_height: 'U height',
  width_mm: 'Outer width', depth_mm: 'Outer depth', height_mm: 'Outer height', rack_unit_width: 'Rack-unit width',
}
const ORDER = Object.keys(PUBLISH_LABELS) as PublishField[]

export function readinessOf(p: Partial<CabinetProfile>): { ready: boolean; missing: string[] } {
  const missing = ORDER.filter((k) => {
    const v = p[k]
    return v == null || v === '' || (typeof v === 'number' && !(v > 0))
  })
  return { ready: missing.length === 0, missing }
}

type Row = Omit<CabinetProfile, 'readiness'>
const blank = (id: number): Row => ({
  id, manufacturer: '', model: '', name: 'Standard', status: 'draft', version: 1, supersedes_cabinet_profile_id: null,
  u_height: null, width_mm: null, depth_mm: null, height_mm: null, rack_unit_width: null,
  front_door: null, rear_door: null, rail_type: null, rail_depth_min_mm: null, rail_depth_max_mm: null,
  usable_width_mm: null, usable_depth_mm: null, weight_capacity_kg: null, color_hex: null, notes: null,
  front_image: null, rear_image: null, rack_count: 0, created_at: '2026-11-01T15:00:00+00:00', updated_at: '2026-11-01T15:00:00+00:00', updated_by: 'admin@demo.local',
  created_by: 'admin@demo.local', published_at: null, published_by: null, retired_at: null, retired_by: null,
})

/** Typed fixtures: one published, one draft missing 2 publish items, one retired; #4 is a clone of #3 (so #3 is in use). */
export const CABINET_FIXTURES: Row[] = [
  { ...blank(1), manufacturer: 'APC', model: 'NetShelter SX AR3300', name: 'Standard', status: 'published', u_height: 42, width_mm: 600, depth_mm: 1070, height_mm: 1991, rack_unit_width: '19in', front_door: 'perforated', rear_door: 'split', rail_type: 'square_hole', rail_depth_min_mm: 180, rail_depth_max_mm: 910, weight_capacity_kg: 1363, color_hex: '#1F1F1F', published_at: '2026-11-02T14:10:00+00:00', published_by: 'admin@demo.local' },
  { ...blank(2), manufacturer: 'Rittal', model: 'TS IT 5528.110', name: 'Standard', u_height: 47, width_mm: 800, height_mm: 2200, front_door: 'perforated', rear_door: 'perforated', notes: 'Depth to confirm from the datasheet.' },
  { ...blank(3), manufacturer: 'Vertiv', model: 'VR3100', name: 'Standard', status: 'retired', u_height: 42, width_mm: 600, depth_mm: 1100, height_mm: 1998, rack_unit_width: '19in', front_door: 'perforated', rear_door: 'split', published_at: '2026-06-01T12:00:00+00:00', published_by: 'admin@demo.local', retired_at: '2026-10-01T12:00:00+00:00', retired_by: 'admin@demo.local' },
  { ...blank(4), manufacturer: 'Vertiv', model: 'VR3100', name: 'Standard (copy)', version: 2, supersedes_cabinet_profile_id: 3, u_height: 42, width_mm: 600, depth_mm: 1100, height_mm: 1998, rack_unit_width: '19in' },
]

const fail = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): never => {
  throw new ApiError(status, message, { detail: { code, message, ...extra } })
}
const key = (r: { manufacturer: string; model: string; name: string }) => [r.manufacturer, r.model, r.name].map((s) => s.trim().toLowerCase()).join('\u0000')

export interface MockSeed { rows?: Row[]; /** actor email for history / updated_by (default admin@demo.local). */ actor?: () => string; /** role the mock checks writes against (default admin). */ role?: () => string | undefined; delayMs?: number }

export function createMockCabinetApi(seed: MockSeed = {}): CabinetProfileApi & { rows: Row[] } {
  const rows: Row[] = structuredClone(seed.rows ?? CABINET_FIXTURES)
  let nextId = Math.max(0, ...rows.map((r) => r.id)) + 1
  const out = (r: Row): CabinetProfile => structuredClone({ ...r, readiness: readinessOf(r) })
  const wait = () => new Promise((res) => setTimeout(res, seed.delayMs ?? 0))
  const admin = () => { if ((seed.role?.() ?? 'admin') !== 'admin') fail(403, 'forbidden', 'Requires role: admin') }
  const find = (id: number) => rows.find((r) => r.id === id) ?? fail(404, 'not_found', 'Cabinet profile not found')
  let tick = 0
  const stamp = () => new Date(Date.UTC(2026, 10, 3, 12, 0, tick++)).toISOString().replace(/\.\d+Z$/, '+00:00')
  const actor = () => seed.actor?.() ?? 'admin@demo.local'
  const touch = (r: Row) => { r.updated_at = stamp(); r.updated_by = actor() }
  // History like GET /cabinet-profiles/{id}/history: newest first, before/after = changed fields only.
  const events: (CabinetHistoryEvent & { profile_id: number })[] = []
  let eventId = 1
  const log = (profile_id: number, action: string, before: Record<string, unknown> | null, after: Record<string, unknown> | null, at = stamp()) =>
    events.push({ id: eventId++, profile_id, occurred_at: at, action: `cabinet_profile.${action}`, actor_email: actor(), before, after })
  const SKIP = new Set(['id', 'readiness', 'front_image', 'rear_image', 'rack_count', 'updated_at', 'updated_by', 'created_at'])
  const diff = (a: Row, b: Row) => {
    const before: Record<string, unknown> = {}, after: Record<string, unknown> = {}
    for (const k of Object.keys(b) as (keyof Row)[]) if (!SKIP.has(k) && JSON.stringify(a[k]) !== JSON.stringify(b[k])) { before[k] = a[k]; after[k] = b[k] }
    return Object.keys(after).length ? { before, after } : null
  }
  const snapshot = (r: Row) => Object.fromEntries(Object.entries(r).filter(([k, v]) => !SKIP.has(k) && v != null))
  const checkName = (r: { manufacturer: string; model: string; name: string }, self?: number) => {
    const dup = rows.find((x) => x.id !== self && key(x) === key(r))
    if (dup) fail(409, 'cabinet_profile_name_taken', `${[dup.manufacturer, dup.model, dup.name].join(' ')} already exists.`, { existing_id: dup.id })
  }
  const checkValues = (b: CabinetProfileInput) => {
    // Schema-level rules (FastAPI → 422 validation list): > 0 only (no upper caps), U 1–100.
    const list: { type: string; loc: string[]; msg: string }[] = []
    for (const k of ['width_mm', 'depth_mm', 'height_mm', 'usable_width_mm', 'usable_depth_mm', 'rail_depth_min_mm', 'rail_depth_max_mm'] as const) {
      const v = b[k]
      if (v == null) continue
      if (!(v > 0)) list.push({ type: 'greater_than', loc: ['body', k], msg: 'Input should be greater than 0' })
    }
    if (b.weight_capacity_kg != null && !(b.weight_capacity_kg > 0)) list.push({ type: 'greater_than', loc: ['body', 'weight_capacity_kg'], msg: 'Input should be greater than 0' })
    if (b.u_height != null && !(Number.isInteger(b.u_height) && b.u_height >= 1 && b.u_height <= 100)) list.push({ type: 'less_than_equal', loc: ['body', 'u_height'], msg: 'Input should be less than or equal to 100' })
    if (list.length) throw new ApiError(422, 'validation', { detail: list })
  }
  const checkDims = (p: Row) => {
    const bad: string[] = []
    if (p.usable_width_mm != null && p.width_mm != null && p.usable_width_mm > p.width_mm) bad.push('usable_width_mm')
    if (p.usable_depth_mm != null && p.depth_mm != null && p.usable_depth_mm > p.depth_mm) bad.push('usable_depth_mm')
    if (p.rail_depth_min_mm != null && p.rail_depth_max_mm != null && p.rail_depth_min_mm > p.rail_depth_max_mm) bad.push('rail_depth_min_mm')
    if (p.rail_depth_max_mm != null && p.depth_mm != null && p.rail_depth_max_mm > p.depth_mm) bad.push('rail_depth_max_mm')
    if (bad.length) fail(422, 'invalid_dimension', 'Usable sizes and rail depths must fit inside the outer size', { fields: bad })
  }
  const transition = (id: number, from: string, to: Row['status']) => {
    const r = find(id)
    if (r.status === to) return out(r)
    if (r.status !== from) fail(422, 'invalid_status_transition', `A ${r.status} profile can't move to ${to}`, { status: r.status, to })
    if (to === 'published') { const rd = readinessOf(r); if (!rd.ready) fail(422, 'cabinet_profile_incomplete', 'This profile is missing required fields', { missing: rd.missing }) }
    const prev = structuredClone(r)
    const now = stamp()
    r.status = to
    if (to === 'published' && from === 'draft') { r.published_at = now; r.published_by = actor() }
    if (to === 'retired') { r.retired_at = now; r.retired_by = actor() }
    if (from === 'retired') { r.retired_at = null; r.retired_by = null } // un-retire clears them
    const d = diff(prev, r)
    log(id, 'update', d?.before ?? null, d?.after ?? null, now)
    log(id, from === 'retired' ? 'unretire' : to === 'published' ? 'publish' : 'retire', { status: from }, { status: to }, now)
    touch(r); return out(r)
  }
  const api: CabinetProfileApi = {
    async history(id, p = {}) {
      await wait(); admin()
      const all = events.filter((e) => e.profile_id === id).sort((a, b) => b.id - a.id).map((e) => { const { profile_id, ...rest } = e; void profile_id; return rest })
      const off = p.offset ?? 0
      return { items: all.slice(off, off + (p.limit ?? 50)), total: all.length }
    },
    async list(p = {}) {
      await wait()
      const q = p.q?.trim().toLowerCase()
      return rows
        .filter((r) => !p.status || p.status === 'all' || r.status === p.status)
        .filter((r) => !q || `${r.manufacturer} ${r.model} ${r.name}`.toLowerCase().includes(q))
        .map(out)
    },
    async get(id) { await wait(); return out(find(id)) },
    async create(b) {
      await wait(); admin()
      const r: Row = { ...blank(nextId), ...b, manufacturer: (b.manufacturer ?? '').trim(), model: (b.model ?? '').trim(), name: (b.name ?? 'Standard').trim() || 'Standard' } as Row
      if (!r.manufacturer || !r.model) throw new ApiError(422, 'validation', { detail: [...(r.manufacturer ? [] : [{ type: 'string_too_short', loc: ['body', 'manufacturer'], msg: 'String should have at least 1 character' }]), ...(r.model ? [] : [{ type: 'string_too_short', loc: ['body', 'model'], msg: 'String should have at least 1 character' }])] })
      checkValues(b); checkDims(r); checkName(r)
      r.id = nextId++; r.status = 'draft'; r.version = 1; touch(r); r.created_at = r.updated_at; r.created_by = actor()
      rows.push(r); log(r.id, 'create', null, snapshot(r)); return out(r)
    },
    async update(id, patch) {
      await wait(); admin()
      const r = find(id)
      if (r.status === 'retired') fail(409, 'cabinet_profile_retired', "A retired profile is read-only; un-retire it or clone it")
      const { expected_updated_at, ...b } = patch
      if (expected_updated_at && expected_updated_at !== r.updated_at) fail(409, 'version_conflict', 'The profile changed since you loaded it; reload and retry', { current_updated_at: r.updated_at, updated_by: r.updated_by })
      for (const k of ['manufacturer', 'model', 'name'] as const) if (k in b && !b[k]) fail(422, 'cabinet_profile_incomplete', `${k} can't be empty`, { missing: [k] })
      checkValues(b)
      const next = { ...r, ...b } as Row
      checkDims(next)
      if (r.status === 'published' && !readinessOf(next).ready) fail(422, 'cabinet_profile_incomplete', 'A published profile must stay complete', { missing: readinessOf(next).missing })
      checkName(next, id)
      const d = diff(r, next)
      Object.assign(r, next); touch(r)
      if (d) log(id, 'update', d.before, d.after)
      return out(r)
    },
    async remove(id) {
      await wait(); admin()
      const r = find(id)
      const newer = rows.find((x) => x.supersedes_cabinet_profile_id === id)
      if (newer) fail(409, 'cabinet_profile_in_use', 'A newer version supersedes this profile; delete that one first or retire this one', { reason: 'superseded', superseded_by: newer.id })
      log(id, 'delete', snapshot(r), null)
      rows.splice(rows.indexOf(r), 1)
    },
    async publish(id) { await wait(); admin(); return transition(id, 'draft', 'published') },
    async retire(id) { await wait(); admin(); return transition(id, 'published', 'retired') },
    async unretire(id) { await wait(); admin(); return transition(id, 'retired', 'published') },
    async clone(id, name) {
      await wait(); admin()
      const src = find(id)
      // No name: first free "<name> (copy)", "(copy 2)", … (never 409); an explicit taken name → 409.
      let n = name || `${src.name} (copy)`
      if (name) checkName({ ...src, name: n })
      else for (let i = 2; rows.some((x) => key(x) === key({ ...src, name: n })); i++) n = `${src.name} (copy ${i})`
      // Like the API: all fields and every image are copied; version + 1; supersedes the source.
      const r: Row = { ...structuredClone(src), id: nextId++, name: n, status: 'draft', version: src.version + 1, supersedes_cabinet_profile_id: src.id, published_at: null, published_by: null, retired_at: null, retired_by: null }
      touch(r); r.created_at = r.updated_at; r.created_by = actor(); rows.push(r)
      log(r.id, 'create', null, snapshot(r))
      log(r.id, 'clone', null, { source_id: src.id, new_id: r.id, image_count: [src.front_image, src.rear_image].filter(Boolean).length })
      return out(r)
    },
    async uploadImage(id, face, file) {
      await wait(); admin()
      const r = find(id)
      if (r.status === 'retired') fail(409, 'cabinet_profile_retired', 'A retired profile is read-only')
      const url = typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : `mock://cabinet/${id}/${face}`
      r[face === 'front' ? 'front_image' : 'rear_image'] = { url, thumb_url: url }
      touch(r); log(id, 'image.put', null, { face }); return out(r)
    },
  }
  return Object.assign(api, { rows })
}
