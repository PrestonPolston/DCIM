// Readable cabinet-profile history from GET /cabinet-profiles/{id}/history (newest first).
// publish / retire / unretire come as two events (the named action + the listener's `update` with the
// status diff); clone comes with the new row's `create`. Pairs at the same moment collapse into one entry.
import type { CabinetHistoryEvent } from '../api/cabinetProfiles'
import { DOOR_TYPES, RACK_UNIT_WIDTHS, RAIL_TYPES } from '../api/cabinetProfiles'
import { PUBLISH_LABELS } from '../api/cabinetProfiles.mock'
import { parseApiDate } from './apiDate'
import { LENGTH_LABELS } from './cabinetForm'

export interface HistoryChange { field: string; label: string; from: string; to: string }
export interface HistoryEntry { id: number; at: string; actor: string | null; title: string; changes: HistoryChange[] }

const LABELS: Record<string, string> = {
  ...PUBLISH_LABELS, ...LENGTH_LABELS, status: 'Status', rail_type: 'Rail holes', front_door: 'Front door', rear_door: 'Rear door',
  weight_capacity_kg: 'Weight capacity', color_hex: 'Colour', notes: 'Notes', version: 'Version',
}
/** Bookkeeping keys not worth showing as a change. */
const HIDDEN = new Set(['id', 'change_set_id', 'created_at', 'updated_at', 'created_by', 'updated_by', 'published_at', 'published_by', 'retired_at', 'retired_by', 'supersedes_cabinet_profile_id', 'sha256', 'byte_size', 'face', 'source_id', 'new_id', 'image_count'])
const ENUMS: Record<string, [string, string][]> = { rack_unit_width: RACK_UNIT_WIDTHS, rail_type: RAIL_TYPES, front_door: DOOR_TYPES, rear_door: DOOR_TYPES }
const NAMED: Record<string, string> = { publish: 'Published', retire: 'Retired', unretire: 'Un-retired' }

export function formatValue(field: string, v: unknown): string {
  if (v == null || v === '') return '—'
  const e = ENUMS[field]?.find(([k]) => k === v)
  if (e) return e[1]
  if (field.endsWith('_mm') && typeof v === 'number') return `${v} mm`
  if (field === 'weight_capacity_kg' && typeof v === 'number') return `${v} kg`
  if (field === 'u_height' && typeof v === 'number') return `${v} U`
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
export function changesOf(before: Record<string, unknown> | null, after: Record<string, unknown> | null): HistoryChange[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].filter((k) => !HIDDEN.has(k))
  return keys.map((k) => ({ field: k, label: LABELS[k] ?? k, from: formatValue(k, before?.[k]), to: formatValue(k, after?.[k]) }))
    .filter((c) => c.from !== c.to)
}
const short = (a: string) => a.replace(/^cabinet_profile\./, '')
const sameMoment = (a: string, b: string) => Math.abs((parseApiDate(a)?.getTime() ?? 0) - (parseApiDate(b)?.getTime() ?? 1e15)) <= 2000

export function collapseHistory(events: CabinetHistoryEvent[]): HistoryEntry[] {
  const out: HistoryEntry[] = []
  const used = new Set<number>()
  for (const e of events) {
    if (used.has(e.id)) continue
    const a = short(e.action)
    // Find this event's partner (named lifecycle ↔ update; clone ↔ create) at the same moment.
    const partnerOf = (want: (x: string) => boolean) => events.find((x) => x.id !== e.id && !used.has(x.id) && want(short(x.action)) && sameMoment(x.occurred_at, e.occurred_at))
    let title: string, changes: HistoryChange[]
    if (NAMED[a] || (a === 'update' && partnerOf((x) => !!NAMED[x]) && e.after && 'status' in e.after)) {
      const named = NAMED[a] ? e : partnerOf((x) => !!NAMED[x])!
      const upd = NAMED[a] ? partnerOf((x) => x === 'update') : e
      ;[named, upd].forEach((x) => x && used.add(x.id))
      title = NAMED[short(named.action)]
      changes = changesOf(upd?.before ?? named.before, upd?.after ?? named.after)
    } else if (a === 'clone' || (a === 'create' && partnerOf((x) => x === 'clone'))) {
      const clone = a === 'clone' ? e : partnerOf((x) => x === 'clone')!
      const create = a === 'clone' ? partnerOf((x) => x === 'create') : e
      ;[clone, create].forEach((x) => x && used.add(x.id))
      const src = clone.after?.source_id, n = clone.after?.image_count
      title = `Created as a copy of profile #${src ?? '?'}${typeof n === 'number' ? ` (${n} image${n === 1 ? '' : 's'} copied)` : ''}`
      changes = []
    } else {
      used.add(e.id)
      const face = (e.after?.face ?? e.before?.face) as string | undefined
      title = a === 'create' ? 'Created' : a === 'update' ? 'Edited' : a === 'delete' ? 'Deleted'
        : a === 'image.put' ? `${face === 'rear' ? 'Rear' : 'Front'} image ${e.before ? 'replaced' : 'uploaded'}`
        : a === 'image.delete' ? `${face === 'rear' ? 'Rear' : 'Front'} image removed` : a
      if (a.startsWith('image.')) {
        const w = e.after?.width_px, h = e.after?.height_px, b = e.after?.byte_size
        const dims = typeof w === 'number' && typeof h === 'number' ? `${w} × ${h} px` : ''
        const size = typeof b === 'number' ? `${(b / 1024).toFixed(1)} KB` : ''
        if (dims || size) title += ` (${[dims, size].filter(Boolean).join(', ')})`
        changes = []
      } else changes = a === 'create' ? changesOf(null, e.after) : a === 'delete' ? [] : changesOf(e.before, e.after)
    }
    out.push({ id: e.id, at: e.occurred_at, actor: e.actor_email, title, changes })
  }
  return out
}
