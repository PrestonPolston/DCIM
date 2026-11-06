// Cabinet profile form state, validation and publish checklist (admin-setup.md §3, §6).
// Lengths are typed in the current unit and stored as whole mm.
import { PUBLISH_FIELDS, type CabinetProfile, type CabinetProfileInput, type DoorType, type PublishField, type RackUnitWidth, type RailType } from '../api/cabinetProfiles'
import { PUBLISH_LABELS } from '../api/cabinetProfiles.mock'
import { mmToInput, parseLength, parsePositive, parseUHeight, type LengthUnit } from './units'

export const LENGTH_FIELDS = ['width_mm', 'depth_mm', 'height_mm', 'rail_depth_min_mm', 'rail_depth_max_mm', 'usable_width_mm', 'usable_depth_mm'] as const
export type LengthField = (typeof LENGTH_FIELDS)[number]
export const LENGTH_LABELS: Record<LengthField, string> = {
  width_mm: 'Outer width', depth_mm: 'Outer depth', height_mm: 'Outer height',
  rail_depth_min_mm: 'Rail depth min', rail_depth_max_mm: 'Rail depth max', usable_width_mm: 'Usable width', usable_depth_mm: 'Usable depth',
}
export { PUBLISH_LABELS }

export interface CabinetForm {
  manufacturer: string
  model: string
  name: string
  uHeight: string
  unit: LengthUnit
  len: Record<LengthField, string>
  rackUnitWidth: RackUnitWidth | ''
  frontDoor: DoorType | ''
  rearDoor: DoorType | ''
  railType: RailType | ''
  maxLoadKg: string
  colorHex: string
  notes: string
  frontImage: File | null
  rearImage: File | null
}

const noLen = (): Record<LengthField, string> => Object.fromEntries(LENGTH_FIELDS.map((k) => [k, ''])) as Record<LengthField, string>
export function emptyCabinetForm(init: Partial<CabinetForm> = {}): CabinetForm {
  return {
    manufacturer: '', model: '', name: 'Standard', uHeight: '53', unit: 'mm', len: noLen(), rackUnitWidth: '19in',
    frontDoor: '', rearDoor: '', railType: '', maxLoadKg: '', colorHex: '', notes: '', frontImage: null, rearImage: null, ...init,
  }
}
export function formFromProfile(p: CabinetProfile, unit: LengthUnit = 'mm'): CabinetForm {
  const len = noLen()
  for (const k of LENGTH_FIELDS) len[k] = mmToInput(p[k], unit)
  return emptyCabinetForm({
    manufacturer: p.manufacturer, model: p.model, name: p.name, uHeight: p.u_height == null ? '' : String(p.u_height), unit, len,
    rackUnitWidth: p.rack_unit_width ?? '', frontDoor: p.front_door ?? '', rearDoor: p.rear_door ?? '', railType: p.rail_type ?? '',
    maxLoadKg: p.weight_capacity_kg == null ? '' : String(p.weight_capacity_kg), colorHex: p.color_hex ?? '', notes: p.notes ?? '',
  })
}

/** Switch the length unit, converting every valid value (invalid text is kept as typed). */
export function switchUnit(f: CabinetForm, unit: LengthUnit): CabinetForm {
  if (unit === f.unit) return f
  const len = { ...f.len }
  for (const k of LENGTH_FIELDS) {
    const r = parseLength(f.len[k], f.unit)
    if (r.ok && !r.empty) len[k] = mmToInput(r.mm, unit)
  }
  return { ...f, unit, len }
}

export type FieldErrors = Partial<Record<LengthField | 'u_height' | 'weight_capacity_kg' | 'color_hex' | 'notes' | 'manufacturer' | 'model' | 'name', string>>

/** Field-level errors for whatever is typed (empty is not an error; the checklist covers required). */
export function validateCabinet(f: CabinetForm): FieldErrors {
  const e: FieldErrors = {}
  for (const k of LENGTH_FIELDS) { const r = parseLength(f.len[k], f.unit); if (!r.ok) e[k] = r.error }
  const u = parseUHeight(f.uHeight); if (!u.ok) e.u_height = u.error
  const kg = parsePositive(f.maxLoadKg); if (!kg.ok) e.weight_capacity_kg = kg.error
  if (f.colorHex.trim() && !/^#[0-9a-f]{6}$/i.test(f.colorHex.trim())) e.color_hex = 'Use a colour like #1F1F1F.'
  if (f.notes.length > 2000) e.notes = 'Notes can be at most 2000 characters.'
  for (const k of ['manufacturer', 'model', 'name'] as const) if (f[k].trim().length > 128) e[k] = 'At most 128 characters.'
  const mn = parseLength(f.len.rail_depth_min_mm, f.unit), mx = parseLength(f.len.rail_depth_max_mm, f.unit)
  if (!e.rail_depth_max_mm && mn.ok && mx.ok && mn.mm != null && mx.mm != null && mn.mm > mx.mm) e.rail_depth_max_mm = 'Max must be at least the min.'
  return e
}

export const lengthMm = (f: CabinetForm, k: LengthField) => { const r = parseLength(f.len[k], f.unit); return r.ok ? r.mm : null }

/** Body for POST/PATCH, always in mm (the API's optional `unit` is not used). */
export function toBody(f: CabinetForm): CabinetProfileInput {
  const u = parseUHeight(f.uHeight), kg = parsePositive(f.maxLoadKg)
  const b: CabinetProfileInput = {
    manufacturer: f.manufacturer.trim(), model: f.model.trim(), name: f.name.trim() || 'Standard',
    u_height: u.ok ? u.value : null, rack_unit_width: f.rackUnitWidth || null,
    front_door: f.frontDoor || null, rear_door: f.rearDoor || null, rail_type: f.railType || null,
    weight_capacity_kg: kg.ok ? kg.value : null, color_hex: f.colorHex.trim() || null, notes: f.notes.trim() || null,
  }
  for (const k of LENGTH_FIELDS) b[k] = lengthMm(f, k)
  return b
}

export const canSaveDraft = (f: CabinetForm) => !!f.manufacturer.trim() && !!f.model.trim() && !!f.name.trim()

export interface ChecklistItem { key: PublishField; label: string; ok: boolean }
const filled: Record<PublishField, (f: CabinetForm) => boolean> = {
  manufacturer: (f) => !!f.manufacturer.trim(), model: (f) => !!f.model.trim(), name: (f) => !!f.name.trim(),
  u_height: (f) => { const r = parseUHeight(f.uHeight); return r.ok && r.value != null },
  width_mm: (f) => lengthMm(f, 'width_mm') != null, depth_mm: (f) => lengthMm(f, 'depth_mm') != null, height_mm: (f) => lengthMm(f, 'height_mm') != null,
  rack_unit_width: (f) => !!f.rackUnitWidth,
}
/** Publish checklist from the form; a server `missing[]` (422 cabinet_profile_not_ready) also marks items. */
export function cabinetChecklist(f: CabinetForm, serverMissing: string[] | null = null): ChecklistItem[] {
  const bad = new Set(serverMissing ?? [])
  return PUBLISH_FIELDS.map((k) => ({ key: k, label: PUBLISH_LABELS[k], ok: filled[k](f) && !bad.has(k) }))
}
/** Checklist for a saved profile, from the server's readiness. */
export function profileChecklist(p: CabinetProfile): ChecklistItem[] {
  const bad = new Set(p.readiness.missing)
  return PUBLISH_FIELDS.map((k) => ({ key: k, label: PUBLISH_LABELS[k], ok: !bad.has(k) }))
}
/** "2 items missing: Outer depth, Rack-unit width." / "Ready to publish." */
export function missingSentence(items: ChecklistItem[]): string {
  const bad = items.filter((i) => !i.ok)
  if (!bad.length) return 'Ready to publish.'
  return `${bad.length} item${bad.length === 1 ? '' : 's'} missing: ${bad.map((i) => i.label).join(', ')}.`
}
export const cabinetTitle = (p: { manufacturer: string; model: string; name: string }) => `${p.manufacturer} ${p.model} · ${p.name}`

/** Client-side filter for cabinet rows (status tab + search), mirroring GET /cabinet-profiles?status=&q=. */
export function filterCabinets(rows: CabinetProfile[], status: string, q: string): CabinetProfile[] {
  const t = q.trim().toLowerCase()
  return rows.filter((r) => (status === 'all' || r.status === status) && (!t || `${r.manufacturer} ${r.model} ${r.name}`.toLowerCase().includes(t)))
}
