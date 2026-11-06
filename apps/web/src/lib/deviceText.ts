// Display text for one device (3D cards, list). Pure.
import { ASSET_LABEL } from '../api/profiles'
import type { RowFrontDevice } from './rowFront'

export function ruRange(d: RowFrontDevice) {
  return d.top_u && d.top_u !== d.position_u ? `U${d.position_u}–${d.top_u}` : `U${d.position_u}`
}
export function serialText(d: RowFrontDevice) {
  if (d.serial_number) return d.serial_number
  return d.serial_note ? `No serial (${d.serial_note})` : 'No serial'
}
export function assetText(d: RowFrontDevice) {
  const a = d.effective_asset_type ?? d.device_type?.asset_type ?? null
  return a ? (ASSET_LABEL as Record<string, string>)[a] ?? a : 'Not set'
}


export function sizeText(d: RowFrontDevice) {
  const u = Math.max(1, (d.top_u ?? d.position_u) - d.position_u + 1)
  return `${ruRange(d)} · ${u}U · ${d.face === 'rear' ? 'rear' : 'front'}`
}
export function depthText(d: RowFrontDevice) {
  const full = d.is_full_depth ?? d.device_type?.is_full_depth ?? true
  const mm = d.depth_mm ? ` (${d.depth_mm} mm)` : ''
  return `${full ? 'Full depth' : 'Half depth'}${mm}`
}
export function modelText(d: RowFrontDevice) {
  const m = [d.manufacturer ?? d.device_type?.manufacturer, d.model ?? d.device_type?.name].filter(Boolean).join(' ')
  return m || null
}
export const ORIENTATION_LABEL = { power_front: 'Power front', port_front: 'Port front' } as const

/** aria-live selection line for the 3D row: "Selected: web-01, Cabinet R12, RU 2–3". */
export function selectionText(d: RowFrontDevice, cabinet: string) {
  return `Selected: ${d.host_name}, Cabinet ${cabinet}, RU ${ruRange(d).slice(1)}`
}
