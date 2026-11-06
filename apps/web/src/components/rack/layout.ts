import type { RowFrontDevice } from '../../lib/rowFront'
// Pure layout logic for the rack elevation (docs/design/rack-elevation.md).
import type { Face } from '../../api/types'

export interface ElevationDevice {
  id: number
  host_name: string
  status: string
  /** Lowest occupied U, 1-based. */
  position_u: number
  /** Device type height in U. */
  height_u: number
  face: Face
  /** Full-depth devices show on both faces (hatched on the opposite one). Default true, matching the API's DeviceType default. */
  is_full_depth?: boolean
  model?: string
  serial_number?: string | null
  /** Profile front art (image or generic by asset type), drawn behind the label; reuses DeviceFront. */
  front?: RowFrontDevice
  /** API needs_review: show the Needs profile badge. */
  needs_review?: boolean
  needs_review_reason?: string | null
}

export interface Block {
  device: ElevationDevice
  top: number // highest U occupied
  bottom: number // = position_u
  /** True when drawn on the face opposite its mounting face. */
  mirrored: boolean
  conflict: boolean
}

export interface FaceLayout {
  blocks: Block[]
  /** Free U numbers on this face, descending. */
  empty: number[]
  unplaced: ElevationDevice[]
  usedU: number
  largestGap: number
  conflicts: number
}

export function occupies(d: ElevationDevice, face: Face): boolean {
  return d.face === face || (d.is_full_depth ?? true)
}

export function layoutFace(rackU: number, devices: ElevationDevice[], face: Face): FaceLayout {
  const unplaced: ElevationDevice[] = []
  const blocks: Block[] = []
  for (const d of devices) {
    const h = Math.max(1, d.height_u)
    const top = d.position_u + h - 1
    if (d.position_u < 1 || top > rackU) {
      if (d.face === face) unplaced.push(d)
      continue
    }
    if (!occupies(d, face)) continue
    blocks.push({ device: d, bottom: d.position_u, top, mirrored: d.face !== face, conflict: false })
  }
  const owner = new Map<number, Block[]>()
  for (const b of blocks) for (let u = b.bottom; u <= b.top; u++) owner.set(u, [...(owner.get(u) ?? []), b])
  let conflicts = 0
  for (const b of blocks) {
    for (let u = b.bottom; u <= b.top; u++) if ((owner.get(u)?.length ?? 0) > 1) b.conflict = true
    if (b.conflict) conflicts++
  }
  const empty: number[] = []
  let gap = 0
  let largestGap = 0
  for (let u = rackU; u >= 1; u--) {
    if (owner.has(u)) {
      gap = 0
    } else {
      empty.push(u)
      largestGap = Math.max(largestGap, ++gap)
    }
  }
  blocks.sort((a, b) => b.top - a.top)
  return { blocks, empty, unplaced, usedU: rackU - empty.length, largestGap, conflicts }
}

/** Group descending U numbers into consecutive runs: [[53..50], [20], ...]. */
export function emptyRuns(empty: number[]): number[][] {
  const runs: number[][] = []
  for (const u of empty) {
    const last = runs[runs.length - 1]
    if (last && last[last.length - 1] === u + 1) last.push(u)
    else runs.push([u])
  }
  return runs
}

export interface Candidate {
  height_u: number
  is_full_depth: boolean
  /** Device being moved (ignored when checking overlaps). */
  excludeId?: number
}

/**
 * Client-side mirror of the API placement rule (docs/API.md): must fit inside
 * the rack, and must not intersect a device on the same face, or any device
 * when either one is full-depth. The API stays authoritative (409).
 */
export function canPlace(
  rackU: number, devices: ElevationDevice[], c: Candidate, position_u: number, face: Face,
): { ok: true } | { ok: false; reason: string } {
  const top = position_u + Math.max(1, c.height_u) - 1
  if (position_u < 1 || top > rackU) return { ok: false, reason: `exceeds RU${rackU}` }
  for (const d of devices) {
    if (d.id === c.excludeId) continue
    const dTop = d.position_u + Math.max(1, d.height_u) - 1
    const intersects = d.position_u <= top && position_u <= dTop
    const blocks = d.face === face || c.is_full_depth || (d.is_full_depth ?? true)
    if (intersects && blocks) return { ok: false, reason: `overlaps ${d.host_name}` }
  }
  return { ok: true }
}
