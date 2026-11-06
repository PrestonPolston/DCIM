// Pure screen-space label layout for the 3D row overlay (cabinet + row names, the hovered/selected
// device's name tag and the ◢ marker). Called synchronously right after each render with that
// render's view-projection matrix, so labels never lag the canvas.
import { RU_M, type Box3D, type Face3D, type RowScene } from './row3d'


export type LabelKind = 'row' | 'cab' | 'tag' | 'marker'
export interface Anchor {
  key: string
  kind: LabelKind
  /** World position. */
  x: number; y: number; z: number
  /** Higher wins overlaps; ties broken by key (stable, no frame-to-frame reshuffling). */
  priority: number
  /** Unscaled label size in CSS px (measured once; 0 = unknown, treated as a point). */
  w: number; h: number
  /** Never culled by overlap or distance (selection marker, selected tag). */
  pinned?: boolean
  /** LOD (row-3d.md §4): shown only while this world height (1 RU) is ≥ `px` on screen (hides at 0.8×). */
  lod?: { world: number; px: number }
}
export interface Placement { key: string; x: number; y: number; scale: number; visible: boolean }

export const LABEL_OPTS = {
  /** Camera distance (world units) at which a label renders at scale 1. */
  refDist: 6,
  minScale: 0.75,
  maxScale: 1.1,
  /** Raw scale (refDist / distance) below which a visible label hides … */
  hideBelow: 0.4,
  /** … and above which a hidden one shows again (hysteresis band). */
  showAbove: 0.5,
  /** Overlap padding: a hidden label needs this much clear space to appear, a shown one keeps its place until overlapped by more than `-keepPad`. */
  showPad: 6,
  keepPad: -3,
}

/** Column-major 4×4 view-projection matrix (three.js `Matrix4.elements`). */
export type Mat4 = ArrayLike<number>

/** World → canvas CSS px. `w` is clip-space w (≈ view depth); w ≤ 0 means behind the camera. */
export function projectPoint(m: Mat4, x: number, y: number, z: number, width: number, height: number) {
  const cx = m[0] * x + m[4] * y + m[8] * z + m[12]
  const cy = m[1] * x + m[5] * y + m[9] * z + m[13]
  const cz = m[2] * x + m[6] * y + m[10] * z + m[14]
  const w = m[3] * x + m[7] * y + m[11] * z + m[15]
  if (w <= 1e-6) return { x: 0, y: 0, w, behind: true }
  const nx = cx / w, ny = cy / w, nz = cz / w
  return { x: (nx + 1) / 2 * width, y: (1 - ny) / 2 * height, w, behind: nz > 1 || nz < -1 }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/**
 * Lays out labels for one frame. `prev` is the set of keys visible last frame (hysteresis);
 * the returned `visible` set feeds the next call. Deterministic for the same inputs.
 */
export function layoutLabels(anchors: Anchor[], m: Mat4, width: number, height: number, prev: ReadonlySet<string>, o = LABEL_OPTS) {
  const order = [...anchors].sort((a, b) =>
    Number(!!b.pinned) - Number(!!a.pinned) || b.priority - a.priority || Number(prev.has(b.key)) - Number(prev.has(a.key)) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
  const taken: { l: number; t: number; r: number; b: number }[] = []
  const out = new Map<string, Placement>()
  const visible = new Set<string>()
  for (const a of order) {
    const p = projectPoint(m, a.x, a.y, a.z, width, height)
    const raw = p.behind ? 0 : o.refDist / p.w
    const scale = a.kind === 'marker' ? 1 : clamp(raw, o.minScale, o.maxScale)
    const was = prev.has(a.key)
    let vis = !p.behind
    if (vis && !a.pinned) vis = raw >= (was ? o.hideBelow : o.showAbove)
    if (vis && a.lod) vis = (a.lod.world * Math.abs(m[5]) / p.w) * height / 2 >= a.lod.px * (was ? 0.8 : 1)
    const hw = (a.w * scale) / 2, hh = (a.h * scale) / 2
    if (vis && (p.x + hw < 0 || p.x - hw > width || p.y + hh < 0 || p.y - hh > height)) vis = false
    if (vis && !a.pinned && a.w > 0) {
      const pad = was ? o.keepPad : o.showPad
      const box = { l: p.x - hw - pad, t: p.y - hh - pad, r: p.x + hw + pad, b: p.y + hh + pad }
      if (taken.some((t) => box.l < t.r && box.r > t.l && box.t < t.b && box.b > t.t)) vis = false
    }
    if (vis) { visible.add(a.key); if (a.w > 0) taken.push({ l: p.x - hw, t: p.y - hh, r: p.x + hw, b: p.y + hh }) }
    out.set(a.key, { key: a.key, x: p.x, y: p.y, scale, visible: vis })
  }
  return { placements: anchors.map((a) => out.get(a.key)!), visible }
}

export interface LabelSpec extends Omit<Anchor, 'w' | 'h'> { text: string; cls: string }

/**
 * What to label: the row name (left end, above), every cabinet name (top centre) when
 * `names` is on, the selected device's name tag and the ◢ marker. Device names are never
 * always-on (Preston, Oct 2026): only the selected tag here, hover uses the hover card.
 */
export function labelSpecs(scene: RowScene, o: { rowName?: string; names: boolean; side: Face3D; tag: { id: number; text: string } | null; marker: number | null; box: (id: number) => Box3D | undefined }): LabelSpec[] {
  const out: LabelSpec[] = []
  const front = o.side === 'front'
  if (o.names && scene.cabinets.length) {
    if (o.rowName) {
      const end = front ? scene.cabinets[0] : scene.cabinets[scene.cabinets.length - 1]
      const half = scene.width / scene.cabinets.length / 2
      out.push({ key: 'row', kind: 'row', text: o.rowName, cls: 'r3d-row-label', x: end.x + (front ? -half : half), y: scene.height + 0.3, z: 0, priority: 3 })
    }
    for (const c of scene.cabinets) out.push({ key: `c${c.id}`, kind: 'cab', text: c.name, cls: 'r3d-cab-label', x: c.x, y: c.height + 0.08, z: 0, priority: 2 })
  }
  const faceZ = (b: Box3D, eps = 0) => (front ? b.cz + b.d / 2 + eps : b.cz - b.d / 2 - eps)
  if (o.tag) {
    const b = o.box(o.tag.id)
    // Just above the device's visible face, centred.
    if (b) out.push({ key: `d${o.tag.id}`, kind: 'tag', text: o.tag.text, cls: 'r3d-dev-label', x: b.cx, y: b.cy + b.h / 2, z: faceZ(b, 0.01), priority: 5, pinned: true, lod: { world: RU_M, px: 14 } })
  }
  if (o.marker != null) {
    const b = o.box(o.marker)
    // Top-left corner of the visible face (screen-left flips from the rear).
    if (b) out.push({ key: 'marker', kind: 'marker', text: '◢', cls: 'r3d-marker', x: b.cx + (front ? -b.w / 2 : b.w / 2), y: b.cy + b.h / 2, z: faceZ(b), priority: 9, pinned: true })
  }
  return out
}

/**
 * Screen polygon of a device's visible face (front face from the front, rear face from the rear),
 * for the 2 px #ffb000 selection outline drawn in the overlay (WebGL lines are 1 px). Null when any
 * corner is behind the camera.
 */
export function faceOutline(b: Box3D, side: Face3D, m: Mat4, width: number, height: number): { x: number; y: number }[] | null {
  const z = side === 'front' ? b.cz + b.d / 2 : b.cz - b.d / 2
  const out: { x: number; y: number }[] = []
  for (const [dx, dy] of [[-1, 1], [1, 1], [1, -1], [-1, -1]]) {
    const p = projectPoint(m, b.cx + (dx * b.w) / 2, b.cy + (dy * b.h) / 2, z, width, height)
    if (p.behind) return null
    out.push({ x: p.x, y: p.y })
  }
  return out
}
