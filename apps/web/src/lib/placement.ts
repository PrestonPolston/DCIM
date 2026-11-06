// Shared placement / move logic (docs/design/row-front.md §4, §9 Frontend 2).
// Used by the row front view, the cabinet elevation and the palette. Pure: no React.
import type { Face } from '../api/types'
import { canPlace, type Candidate, type ElevationDevice } from '../components/rack/layout'

export { canPlace, type Candidate }

export interface Spot { rackId: number; rackName: string; position_u: number; face: Face }
export interface MoveBody { rack_id: number; position_u: number; face: Face }

const faceLabel = (f: Face) => (f === 'front' ? 'Front' : 'Rear')
/** "Move web-01: C-B04 RU20 Front → C-B07 RU12 Front" */
export function describeMove(host: string, from: Spot, to: Spot): string {
  return `Move ${host}: ${from.rackName} RU${from.position_u} ${faceLabel(from.face)} → ${to.rackName} RU${to.position_u} ${faceLabel(to.face)}`
}
export const moveBody = (s: Spot): MoveBody => ({ rack_id: s.rackId, position_u: s.position_u, face: s.face })
export const sameSpot = (a: Spot, b: Spot) => a.rackId === b.rackId && a.position_u === b.position_u && a.face === b.face

/** Fit check against a target cabinet, ignoring the device being moved. */
export function checkFit(rackU: number, devices: ElevationDevice[], moving: ElevationDevice, position_u: number, face: Face) {
  return canPlace(rackU, devices, { height_u: moving.height_u, is_full_depth: moving.is_full_depth ?? true, excludeId: moving.id }, position_u, face)
}

/** Top-of-device RU → lowest RU (position_u) for a device of height h. */
export const positionFromTop = (top: number, h: number) => top - Math.max(1, h) + 1

/** Pixels per frame to auto-scroll when the pointer is within `edge` px of a side (§4: ≤ 20 px/frame). */
export function autoScrollDelta(pos: number, size: number, edge = 48, max = 20): number {
  if (pos < edge) return -Math.ceil(((edge - Math.max(0, pos)) / edge) * max)
  if (pos > size - edge) return Math.ceil(((Math.min(size, pos) - (size - edge)) / edge) * max)
  return 0
}

/** Keyboard move mode (M → arrows/F → Enter). cols = cabinets in on-screen order. */
export interface KeyMove { col: number; position_u: number; face: Face }
export function keyMoveStep(m: KeyMove, key: string, cols: { u: number }[], h: number): KeyMove | null {
  const maxPos = (ci: number) => Math.max(1, cols[ci].u - Math.max(1, h) + 1)
  switch (key) {
    case 'ArrowUp': return { ...m, position_u: Math.min(maxPos(m.col), m.position_u + 1) }
    case 'ArrowDown': return { ...m, position_u: Math.max(1, m.position_u - 1) }
    case 'ArrowLeft': return m.col > 0 ? { ...m, col: m.col - 1, position_u: Math.min(maxPos(m.col - 1), m.position_u) } : m
    case 'ArrowRight': return m.col < cols.length - 1 ? { ...m, col: m.col + 1, position_u: Math.min(maxPos(m.col + 1), m.position_u) } : m
    case 'f': case 'F': return { ...m, face: m.face === 'front' ? 'rear' : 'front' }
    default: return null
  }
}
