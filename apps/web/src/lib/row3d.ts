// Pure scene math for the 3D row view (docs/design/row-3d.md §2–§5, ROW_3D_SPIKE.md).
// No React, DOM or three.js: plain numbers in meters so it is unit-testable and
// shared with the 2D row front ordering (lib/rowFront.cabinetOrder).
import type { RowFrontDevice, RowFrontRack } from './rowFront'

export const RU_M = 0.04445
export const CAB_W = 0.6
export const CAB_D = 1.2
export const FACE_W = 0.4826
export const BASE_Y = 0.1
export const ROOF_H = 0.1
/** Front rail is 100 mm behind the front plane (+z = aisle); rear rail 800 mm behind it. */
export const FRONT_Z = CAB_D / 2
export const RAIL_F = FRONT_Z - 0.1
export const RAIL_R = RAIL_F - 0.8
export const FULL_D = RAIL_F - RAIL_R
export const HALF_D = 0.45
const BLANK_D = 0.02
const CABLE_MGR_D = 0.1

export type Face3D = 'front' | 'rear'

export interface Cabinet3D { id: number; name: string; index: number; x: number; uHeight: number; height: number }
export interface Box3D {
  deviceId: number; rackId: number; cabIndex: number
  /** Center and size in meters. */
  cx: number; cy: number; cz: number; w: number; h: number; d: number
  /** Texture keys for the +z and −z faces (image URL, or `generic:<face>:<asset>`). */
  plusZ: string; minusZ: string
  status: string
}
export interface RowScene {
  cabinets: Cabinet3D[]; boxes: Box3D[]; width: number; height: number
  /** Thumb texture key → close-up URL: tex_url (1024 px WebP), else the original (older servers). LRU-capped. */
  full: Record<string, string>
}

export const cabinetHeight = (u: number) => BASE_Y + u * RU_M + ROOF_H

export function genericKey(face: Face3D, asset: string | null | undefined) {
  return `generic:${face}:${asset || 'other'}`
}
export const isGenericKey = (k: string) => k.startsWith('generic:')

/** Close-up texture for nearby/focused cabinets: the 1024 px `tex` variant when the API sends it, else the original. */
export const closeUpUrl = (im: { url: string; tex_url?: string }) => im.tex_url || im.url

/** Cabinets that get close-up textures: the focused one first, then its neighbours. */
export const closeUpCabinets = (focus: number, count: number) => [focus, focus - 1, focus + 1].filter((i) => i >= 0 && i < count)

/** The texture key a device shows on its own front/rear (thumb first; the LRU upgrades on focus). */
export function faceImage(d: RowFrontDevice, face: Face3D) {
  const asset = d.effective_asset_type ?? d.device_type?.asset_type ?? null
  if (asset === 'blank') return d.effective_front_image ?? null
  if (asset === 'cable_manager' && face === 'rear') return null
  return (face === 'front' ? d.effective_front_image : d.effective_rear_image) ?? null
}
export function faceKey(d: RowFrontDevice, face: Face3D): string {
  const asset = d.effective_asset_type ?? d.device_type?.asset_type ?? null
  const img = faceImage(d, face)
  if (img) return img.thumb_url
  return genericKey(asset === 'blank' ? 'front' : face, asset)
}

/**
 * Box depth (metres).
 * - Full depth: always rail to rail, deliberately IGNORING depth_mm (Designer, v1). A 700 mm server
 *   drawn at its true depth would end short of the rear rail, and its rear photo would float inside
 *   the cabinet, hidden behind the rear doorway, which defeats the Rear view. depth_mm stays in the
 *   payload/adapter (api/rowFront depthOf) and is shown in the detail card.
 * - Half depth: its TRUE depth from depth_mm, hung from its mounting rail (front or rear face); 450 mm
 *   when depth_mm is unknown; capped at rail to rail. Mounting (19"/23"/shelf…) doesn't change depth.
 */
export function deviceDepth(d: RowFrontDevice): number {
  const asset = d.effective_asset_type ?? d.device_type?.asset_type ?? null
  if (asset === 'blank') return BLANK_D
  if (asset === 'cable_manager') return CABLE_MGR_D
  const full = d.is_full_depth ?? d.device_type?.is_full_depth ?? true
  if (full) return FULL_D
  const mm = d.depth_mm && d.depth_mm > 0 ? d.depth_mm / 1000 : null
  return Math.min(FULL_D, mm ?? HALF_D)
}

/** Cabinets left→right as seen from the FRONT (pass lib/rowFront.cabinetOrder(..., 'front').racks). */
export function buildRowScene(racks: RowFrontRack[]): RowScene {
  const n = racks.length
  const width = n * CAB_W
  const cabinets: Cabinet3D[] = racks.map((r, i) => ({
    id: r.id, name: r.name, index: i, x: i * CAB_W - width / 2 + CAB_W / 2, uHeight: r.u_height, height: cabinetHeight(r.u_height),
  }))
  const boxes: Box3D[] = []
  const full: Record<string, string> = {}
  racks.forEach((r, i) => {
    for (const d of r.devices) {
      if (d.position_u == null) continue
      const u = Math.max(1, (d.top_u ?? d.position_u) - d.position_u + 1)
      const h = u * RU_M - 0.002
      const depth = deviceDepth(d)
      const rear = d.face === 'rear'
      // Front-mounted hangs from the front rail toward the rear; rear-mounted from the rear rail toward the front.
      const cz = rear ? RAIL_R + depth / 2 : RAIL_F - depth / 2
      const own = { front: faceKey(d, 'front'), rear: faceKey(d, 'rear') }
      for (const f of ['front', 'rear'] as const) {
        const im = faceImage(d, f)
        const close = im ? closeUpUrl(im) : null
        if (im && close && close !== im.thumb_url) full[im.thumb_url] = close
      }
      boxes.push({
        deviceId: d.id, rackId: r.id, cabIndex: i,
        cx: cabinets[i].x, cy: BASE_Y + (d.position_u - 1) * RU_M + u * RU_M / 2, cz,
        w: FACE_W, h, d: depth,
        plusZ: rear ? own.rear : own.front, minusZ: rear ? own.front : own.rear,
        status: d.status,
      })
    }
  })
  const height = Math.max(cabinetHeight(53), ...cabinets.map((c) => c.height))
  return { cabinets, boxes, width, height, full }
}

/** Group boxes that share both face textures: one InstancedMesh (3 draw calls) per group. */
export function groupBoxes(boxes: Box3D[]): Map<string, Box3D[]> {
  const m = new Map<string, Box3D[]>()
  for (const b of boxes) {
    const k = `${b.plusZ}|${b.minusZ}`
    const arr = m.get(k)
    if (arr) arr.push(b); else m.set(k, [b])
  }
  return m
}

// ---- Camera (row-3d.md §3) ---------------------------------------------------
export type V3 = [number, number, number]
export interface CameraPose { position: V3; target: V3 }
const FOV = 40

/** Distance that fits `span` meters into the view (vertical FOV 40°, aspect w/h). */
export function fitDistance(spanW: number, spanH: number, aspect: number): number {
  const t = Math.tan((FOV / 2) * Math.PI / 180)
  return Math.max(spanH / 2 / t, spanW / 2 / (t * Math.max(aspect, 0.1))) * 1.08
}

export function presetPose(kind: 'front' | 'rear' | 'reset' | 'fit', scene: RowScene, aspect: number): CameraPose {
  const ty = scene.height / 2
  const dist = Math.min(22, Math.max(1.5, fitDistance(scene.width + 0.4, scene.height + 0.3, aspect)))
  if (kind === 'reset') {
    const a = -Math.PI / 6
    return { position: [Math.sin(a) * -dist, ty + dist * 0.25, Math.cos(a) * dist], target: [0, ty, 0] }
  }
  const z = kind === 'rear' ? -dist : dist
  return { position: [0, ty, z + (kind === 'rear' ? -FRONT_Z : FRONT_Z)], target: [0, ty, 0] }
}

/** Straight-on view of one cabinet from the given side. */
export function cabinetPose(cab: Cabinet3D, side: Face3D, aspect: number): CameraPose {
  const ty = cab.height / 2
  const dist = Math.max(1.2, fitDistance(CAB_W * 1.6, cab.height + 0.2, aspect))
  const z = side === 'rear' ? -(dist + FRONT_Z) : dist + FRONT_Z
  return { position: [cab.x, ty, z], target: [cab.x, ty, 0] }
}

/** 180° orbit around the target's vertical axis (Flip to rear/front). */
export function flipPose(p: CameraPose): CameraPose {
  const [px, py, pz] = p.position
  const [tx, , tz] = p.target
  return { position: [2 * tx - px, py, 2 * tz - pz], target: p.target }
}

/** Which side the camera is on (z of the camera relative to the target). */
export const sideOf = (p: CameraPose): Face3D => (p.position[2] - p.target[2] >= 0 ? 'front' : 'rear')

export function lerpPose(a: CameraPose, b: CameraPose, t: number): CameraPose {
  const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2 // ease-in-out
  const mix = (x: V3, y: V3): V3 => [x[0] + (y[0] - x[0]) * e, x[1] + (y[1] - x[1]) * e, x[2] + (y[2] - x[2]) * e]
  return { position: mix(a.position, b.position), target: mix(a.target, b.target) }
}

/** Flip animation: orbit (not a straight line through the row) by rotating about the target. */
export function orbitPose(a: CameraPose, t: number): CameraPose {
  const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
  const [tx, , tz] = a.target
  const dx = a.position[0] - tx, dz = a.position[2] - tz
  const ang = Math.PI * e
  return { position: [tx + dx * Math.cos(ang) + dz * Math.sin(ang), a.position[1], tz - dx * Math.sin(ang) + dz * Math.cos(ang)], target: a.target }
}

// ---- Highlight (Status only, decision 8) and keyboard -----------------------
/** 3D status tints (row-3d.md / design-system: Install #ffb454 never the amber selection). */
export const STATUS_TINT: Record<string, number> = { active: 0x4ccf73, install: 0xffb454, decom: 0x8a919c }

/** Arrow-key navigation: ↑/↓ within the cabinet, ←/→ to the nearest-RU device in the next cabinet. */
export function navigate(racks: RowFrontRack[], selectedId: number | null, key: string, side: Face3D = 'front'): number | null {
  const placed = racks.map((r) => [...r.devices].filter((d) => d.position_u != null).sort((a, b) => a.position_u - b.position_u))
  const firstAny = placed.find((l) => l.length)?.[0]
  if (selectedId == null) return firstAny?.id ?? null
  const ci = placed.findIndex((l) => l.some((d) => d.id === selectedId))
  if (ci < 0) return firstAny?.id ?? null
  const list = placed[ci]
  const di = list.findIndex((d) => d.id === selectedId)
  const cur = list[di]
  if (key === 'ArrowUp') return (list[di + 1] ?? cur).id
  if (key === 'ArrowDown') return (list[di - 1] ?? cur).id
  if (key === 'ArrowLeft' || key === 'ArrowRight') {
    // From the rear, screen-left is the next cabinet in front order.
    const dir = (key === 'ArrowRight' ? 1 : -1) * (side === 'rear' ? -1 : 1)
    for (let c = ci + dir; c >= 0 && c < placed.length; c += dir) {
      if (!placed[c].length) continue
      return placed[c].reduce((best, d) => (Math.abs(d.position_u - cur.position_u) < Math.abs(best.position_u - cur.position_u) ? d : best)).id
    }
    return cur.id
  }
  return cur.id
}
