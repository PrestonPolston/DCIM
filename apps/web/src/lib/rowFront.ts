// Pure logic for the row front view (docs/design/row-front.md). No React/DOM.
import type { Face } from '../api/types'
import { layoutFace, emptyRuns, type ElevationDevice } from '../components/rack/layout'
import { statusLabel } from './status'
import { drawAsPlaceholder, needsProfile } from './needsProfile'
import { DEFAULT_RACK_U, rackU } from './rack'
import { layoutHall, type Dir, type HallSettings, type LayoutRowIn } from './hallLayout'

// ---- Data shape: the spec's GET /rows/{id}/front (§9 Backend 1) -------------
export interface FrontImage { url: string; thumb_url: string; tex_url?: string; etag?: string; width_px?: number; height_px?: number }
export interface RowFrontDeviceType {
  id: number; manufacturer: string; name: string; u_height: number; is_full_depth: boolean; asset_type?: string | null
}
export interface RowFrontDevice {
  id: number; host_name: string; status: string
  serial_number: string | null; serial_unavailable?: boolean | null; serial_note?: string | null
  position_u: number; top_u: number; face: Face
  device_type: RowFrontDeviceType | null
  profile_id?: number | null
  effective_asset_type?: string | null
  /** Null/undefined → FallbackFront. Not served by the API yet (docs/db/PROFILE_IMAGES.md). */
  effective_front_image?: FrontImage | null
  /** Profile rear image (HEAD). Null → generic rear art. */
  effective_rear_image?: FrontImage | null
  /** From the profile (HEAD); default full depth when unknown. */
  is_full_depth?: boolean
  mounting?: 'rack_19in' | 'rack_23in' | 'shelf' | 'zero_u' | 'other' | null
  depth_mm?: number | null
  /** Elevation/row items (HEAD 6dd3f05); fall back to device_type when absent. */
  manufacturer?: string | null
  model?: string | null
  weight_kg?: number | null
  /** Profile orientation (switches): not in HEAD yet → omitted badge. */
  orientation?: 'power_front' | 'port_front' | null
  needs_review?: boolean | null
  needs_review_reason?: string | null
}
export interface RowFrontRack {
  id: number; name: string; u_height: number
  pos_x: number | null; pos_y: number | null
  effective_orientation: Dir | null
  u_used: number; u_free: number
  devices: RowFrontDevice[]
}
export interface RowFrontData {
  row: { id: number; name: string; hall_id: number; orientation: Dir | null; effective_facing: Dir | null }
  hall: { id: number; name: string; aisle_axis: 'x' | 'y' | null; odd_side: 'low' | 'high' | null }
  racks: RowFrontRack[]
}

// ---- Facing (reuses lib/hallLayout) ----------------------------------------
/** Hall API hint (aisle_axis/odd_side) → plan settings; browser-local settings win when saved. */
export function settingsFromHint(hall: RowFrontData['hall'], local: HallSettings | null, fallback: HallSettings): HallSettings {
  if (local) return local
  if (!hall.aisle_axis) return fallback
  return {
    ...fallback,
    aisle: hall.aisle_axis === 'x' ? 'horizontal' : 'vertical',
    oddSide: hall.odd_side === 'high' ? 'end' : 'start',
  }
}

/** The row's front direction: most common cabinet facing from layoutHall (API orientation first). */
export function rowFacing(rows: LayoutRowIn[], rowId: number, settings: HallSettings): Dir | null {
  const counts = new Map<Dir, number>()
  for (const c of layoutHall(rows, settings).cabinets) {
    if (c.rowId === rowId && c.facing) counts.set(c.facing, (counts.get(c.facing) ?? 0) + 1)
  }
  let best: Dir | null = null
  for (const [d, n] of counts) if (!best || n > counts.get(best)!) best = d
  return best
}

// ---- §7 cabinet order -------------------------------------------------------
const natural = (a: { name: string; id: number }, b: { name: string; id: number }) =>
  a.name.localeCompare(b.name, undefined, { numeric: true }) || a.id - b.id

const OPP: Record<Dir, Dir> = { N: 'S', S: 'N', E: 'W', W: 'E' }
/** Compass direction at the viewer's left / right for the front view (viewer looks opposite to facing). */
const LEFT_RIGHT: Record<Dir, [Dir, Dir]> = { S: ['W', 'E'], N: ['E', 'W'], E: ['S', 'N'], W: ['N', 'S'] }

export interface CabinetOrder<T> { racks: T[]; note: string | null; left: Dir | null; right: Dir | null }

/**
 * Left→right order standing in the aisle (§7 table). Along-row axis is x for
 * N/S-facing rows and y for E/W; when any cabinet lacks that coordinate,
 * natural name order stands in for it (same order layoutHall auto-places in).
 */
export function cabinetOrder<T extends { id: number; name: string; pos_x: number | null; pos_y: number | null }>(
  racks: T[], facing: Dir | null, face: Face,
): CabinetOrder<T> {
  const list = [...racks].sort(natural)
  let left: Dir | null = null
  let right: Dir | null = null
  if (facing) {
    const axis = facing === 'N' || facing === 'S' ? 'pos_x' : 'pos_y'
    if (list.every((r) => r[axis] != null)) list.sort((a, b) => a[axis]! - b[axis]! || natural(a, b))
    const descending = facing === 'N' || facing === 'E'
    if (descending) list.reverse()
    ;[left, right] = LEFT_RIGHT[facing]
  }
  if (face === 'rear') {
    list.reverse()
    if (left && right) [left, right] = [right, left]
  }
  return { racks: list, note: facing ? null : 'Facing not set', left, right }
}
export const opposite = (d: Dir) => OPP[d]

// ---- §1/§2 scale and level of detail ----------------------------------------
export const RU_FIT_MIN = 6
export const RU_FIT_MAX = 12
export const ZOOM_LEVELS = [6, 8, 12, 16, 24, 32, 48] as const
export const PHONE_DETAIL_RU = 20
export const CW_MIN = 24
export type Lod = 0 | 1 | 2

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
/** Fit row: ru = clamp(6, floor(availH / 53), 12). */
export function fitRu(availH: number, rowU = DEFAULT_RACK_U): number {
  return clamp(Math.floor(availH / rowU), RU_FIT_MIN, RU_FIT_MAX)
}
/** Fit row column width; below CW_MIN the row scrolls horizontally. */
export function fitCw(availW: number, n: number, ruler: number, gap: number): number {
  if (n <= 0) return CW_MIN
  return Math.max(CW_MIN, Math.floor((availW - ruler - (n - 1) * gap) / n))
}
/** Detail width follows the 19-inch proportion: cw = round(ru × 10). */
export const detailCw = (ru: number) => Math.max(CW_MIN, Math.round(ru * 10))
export function lod(ru: number): Lod {
  return ru < 10 ? 0 : ru < 20 ? 1 : 2
}
export function zoomStep(ru: number, dir: 1 | -1): number {
  if (dir > 0) return ZOOM_LEVELS.find((z) => z > ru) ?? ZOOM_LEVELS[ZOOM_LEVELS.length - 1]
  return [...ZOOM_LEVELS].reverse().find((z) => z < ru) ?? ZOOM_LEVELS[0]
}
/** Viewport → chrome-free size, gap and ruler width (§1 table). */
export function viewportMetrics(width: number): { gap: number; ruler: number; phone: boolean } {
  if (width < 600) return { gap: 2, ruler: 24, phone: true }
  if (width < 1100) return { gap: width < 900 ? 4 : 6, ruler: 32, phone: false }
  return { gap: 8, ruler: 40, phone: false }
}
/** Ruler labels: 1, 5, 10 … 50 and the top RU. */
export function rulerLabels(rowU: number): number[] {
  const out = [1]
  for (let u = 5; u < rowU; u += 5) out.push(u)
  if (rowU > 1) out.push(rowU)
  return out
}

// ---- §5 fallback category ---------------------------------------------------
export type Category = 'server' | 'switch' | 'patch' | 'pdu' | 'cable' | 'other' | 'unknown'
const KEYWORDS: [Category, string[]][] = [
  ['cable', ['cable_manager', 'cable manager', 'cable mgr']],
  ['server', ['server', 'compute', 'gpu', 'storage']],
  ['switch', ['switch', 'router', 'network', 'firewall']],
  ['patch', ['patch', 'panel', 'fiber', 'mpo']],
  ['pdu', ['pdu', 'power', 'ups', 'ats']],
  ['other', ['blank', 'filler', 'shelf', 'other']],
]
export function categoryOf(text: string | null | undefined): Category {
  const t = (text ?? '').toLowerCase()
  for (const [cat, words] of KEYWORDS) if (words.some((w) => t.includes(w))) return cat
  return 'other'
}
/**
 * effective_asset_type → category; no device type → unknown.
 * INTERIM: the elevation API has no asset_type yet, so the type's manufacturer + name is matched instead.
 */
export function deviceCategory(d: RowFrontDevice): Category {
  if (!d.device_type) return 'unknown'
  const src = d.effective_asset_type ?? d.device_type.asset_type ?? `${d.device_type.manufacturer} ${d.device_type.name}`
  return categoryOf(src)
}
export const CATEGORY_LABEL: Record<Category, string> = {
  server: 'SERVER', switch: 'SWITCH', patch: 'PATCH PANEL', pdu: 'PDU', cable: 'CABLE MANAGER', other: 'OTHER', unknown: 'Unknown',
}

export const isNoSerial = (d: RowFrontDevice) => !!d.serial_unavailable || !d.serial_number
export const deviceU = (d: RowFrontDevice) => (drawAsPlaceholder(d) ? 1 : Math.max(1, d.device_type?.u_height ?? 1))
export const deviceFullDepth = (d: RowFrontDevice) => (drawAsPlaceholder(d) ? true : d.device_type?.is_full_depth ?? true)

export function toElevationDevice(d: RowFrontDevice): ElevationDevice {
  return {
    id: d.id, host_name: d.host_name, status: d.status, position_u: d.position_u, face: d.face,
    height_u: deviceU(d), is_full_depth: deviceFullDepth(d), model: d.device_type?.name, serial_number: d.serial_number,
    needs_review: needsProfile(d), needs_review_reason: d.needs_review_reason ?? null,
  }
}

// ---- Column model -----------------------------------------------------------
export type ColItem =
  | { kind: 'device'; top: number; bottom: number; device: RowFrontDevice; passThrough: boolean; conflict: boolean }
  | { kind: 'empty'; top: number; bottom: number }
export interface Column {
  rack: RowFrontRack
  u: number
  /** Descending by top U; devices and empty runs tile 1..u without gaps (conflicts aside). */
  items: ColItem[]
  /** Half-depth devices mounted on the other face: dashed outline "rear: host" only. */
  behind: RowFrontDevice[]
}

export function buildColumn(rack: RowFrontRack, face: Face): Column {
  const u = rackU(rack)
  const byId = new Map(rack.devices.map((d) => [d.id, d]))
  const fl = layoutFace(u, rack.devices.map(toElevationDevice), face)
  const items: ColItem[] = fl.blocks.map((b) => ({
    kind: 'device', top: b.top, bottom: b.bottom, device: byId.get(b.device.id)!, passThrough: b.mirrored, conflict: b.conflict,
  }))
  for (const run of emptyRuns(fl.empty)) items.push({ kind: 'empty', top: run[0], bottom: run[run.length - 1] })
  items.sort((a, b) => b.top - a.top)
  const behind = rack.devices.filter((d) => d.face !== face && !deviceFullDepth(d) && d.position_u >= 1 && d.position_u + deviceU(d) - 1 <= u)
  return { rack, u, items, behind }
}

export const rowHeightU = (racks: { u_height?: number | null }[]) =>
  racks.length ? Math.max(...racks.map((r) => rackU(r))) : DEFAULT_RACK_U

// ---- §3 keyboard grid navigation -------------------------------------------
export interface Cursor { col: number; u: number }
export function itemAt(col: Column, u: number): ColItem | undefined {
  return col.items.find((i) => i.bottom <= u && u <= i.top)
}
/** Next cursor for a grid key, or null when the key isn't a navigation key. Cursor u is the item's top. */
export function navigate(cols: Column[], cur: Cursor, key: string): Cursor | null {
  if (cols.length === 0) return null
  const col = cols[cur.col]
  const land = (ci: number, u: number): Cursor => {
    const c = cols[ci]
    const uu = clamp(u, 1, c.u)
    const it = itemAt(c, uu)
    return { col: ci, u: it ? it.top : uu }
  }
  const idx = col.items.findIndex((i) => i.bottom <= cur.u && cur.u <= i.top)
  switch (key) {
    case 'ArrowUp': return idx > 0 ? { col: cur.col, u: col.items[idx - 1].top } : cur
    case 'ArrowDown': return idx >= 0 && idx < col.items.length - 1 ? { col: cur.col, u: col.items[idx + 1].top } : cur
    case 'ArrowLeft': return cur.col > 0 ? land(cur.col - 1, cur.u) : cur
    case 'ArrowRight': return cur.col < cols.length - 1 ? land(cur.col + 1, cur.u) : cur
    case 'Home': return land(0, cur.u)
    case 'End': return land(cols.length - 1, cur.u)
    case 'PageUp': return land(cur.col, cur.u + 10)
    case 'PageDown': return land(cur.col, cur.u - 10)
    default: return null
  }
}

// ---- Footer summary ----------------------------------------------------------
export function rowSummary(racks: RowFrontRack[]) {
  const status = new Map<string, number>()
  let used = 0
  let total = 0
  let noSerial = 0
  for (const r of racks) {
    used += r.u_used
    total += rackU(r)
    for (const d of r.devices) {
      status.set(d.status, (status.get(d.status) ?? 0) + 1)
      if (isNoSerial(d)) noSerial++
    }
  }
  return { used, total, status, noSerial }
}

/** "web-01, Active, cabinet C-B04, RU 20 to 21, front" (§3). */
export function deviceAria(d: RowFrontDevice, rackName: string, passThrough: boolean): string {
  const top = d.position_u + deviceU(d) - 1
  const ru = top === d.position_u ? `RU ${top}` : `RU ${d.position_u} to ${top}`
  return [d.host_name, statusLabel(d.status), `cabinet ${rackName}`, ru, passThrough ? `${d.face}-mounted, pass-through` : d.face, isNoSerial(d) ? 'no serial' : null, needsProfile(d) ? 'needs profile' : null]
    .filter(Boolean).join(', ')
}

