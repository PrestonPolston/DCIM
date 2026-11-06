import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { faceOutline, layoutLabels, labelSpecs, projectPoint, type Anchor } from './labels'
import { buildRowScene } from './row3d'

function cam(z = 6) {
  const c = new THREE.PerspectiveCamera(50, 800 / 600, 0.1, 100)
  c.position.set(0, 0, z); c.lookAt(0, 0, 0); c.updateMatrixWorld()
  return new THREE.Matrix4().multiplyMatrices(c.projectionMatrix, c.matrixWorldInverse).elements
}
const A = (key: string, x: number, o: Partial<Anchor> = {}): Anchor => ({ key, kind: 'cab', x, y: 0, z: 0, priority: 2, w: 60, h: 16, ...o })

describe('projectPoint', () => {
  it('matches three.js Vector3.project and flags points behind the camera', () => {
    const c = new THREE.PerspectiveCamera(50, 800 / 600, 0.1, 100)
    c.position.set(1, 2, 5); c.lookAt(0, 0, 0); c.updateMatrixWorld()
    const m = new THREE.Matrix4().multiplyMatrices(c.projectionMatrix, c.matrixWorldInverse).elements
    const v = new THREE.Vector3(0.3, -0.4, 0.2).project(c)
    const p = projectPoint(m, 0.3, -0.4, 0.2, 800, 600)
    expect(p.x).toBeCloseTo((v.x + 1) / 2 * 800, 6)
    expect(p.y).toBeCloseTo((1 - v.y) / 2 * 600, 6)
    expect(projectPoint(m, 2, 4, 10, 800, 600).behind).toBe(true)
  })
})

describe('layoutLabels', () => {
  it('centres at the projected anchor and clamps scale by distance', () => {
    const near = layoutLabels([A('a', 0)], cam(2), 800, 600, new Set()).placements[0]
    expect(near).toMatchObject({ x: 400, y: 300, visible: true, scale: 1.1 })
    const mid = layoutLabels([A('a', 0)], cam(10), 800, 600, new Set()).placements[0]
    expect(mid.scale).toBe(0.75) // clamped, raw 0.6 still visible
    expect(mid.visible).toBe(true)
  })

  it('hides tiny labels with hysteresis (hide < 0.4, show > 0.5)', () => {
    const at13 = cam(13) // raw ≈ 0.46: inside the band
    expect(layoutLabels([A('a', 0)], at13, 800, 600, new Set(['a'])).placements[0].visible).toBe(true)
    expect(layoutLabels([A('a', 0)], at13, 800, 600, new Set()).placements[0].visible).toBe(false)
    expect(layoutLabels([A('a', 0)], cam(20), 800, 600, new Set(['a'])).placements[0].visible).toBe(false)
  })

  it('culls overlaps by stable priority, keeps the incumbent, never culls pinned', () => {
    const m = cam(6)
    const r1 = layoutLabels([A('b', 0.02), A('a', 0)], m, 800, 600, new Set())
    expect(r1.placements.map((p) => p.visible)).toEqual([false, true]) // tie → key order
    // 'b' already showing: it keeps its place against an equal-priority newcomer.
    const r2 = layoutLabels([A('b', 0.02), A('a', 0)], m, 800, 600, new Set(['b']))
    expect(r2.placements.map((p) => p.visible)).toEqual([true, false])
    const r3 = layoutLabels([A('b', 0.02, { priority: 1 }), A('row', 0, { priority: 3 }), A('tag', 0.01, { pinned: true, kind: 'tag' })], m, 800, 600, new Set(['b']))
    expect(Object.fromEntries(r3.placements.map((p) => [p.key, p.visible]))).toEqual({ b: false, row: false, tag: true })
  })

  it('is stable frame to frame (no toggling) for an unchanged camera', () => {
    const as = [A('a', 0), A('b', 0.05), A('c', 0.6), A('d', -0.6)]
    let vis = new Set<string>()
    const seen: string[] = []
    for (let i = 0; i < 5; i++) { const r = layoutLabels(as, cam(6), 800, 600, vis); vis = r.visible; seen.push([...vis].sort().join()) }
    expect(new Set(seen).size).toBe(1)
  })

  it('hides off-screen and behind-camera anchors', () => {
    const r = layoutLabels([A('off', 50), A('behind', 0, { z: 20 })], cam(6), 800, 600, new Set())
    expect(r.placements.every((p) => !p.visible)).toBe(true)
  })
})

describe('labelSpecs', () => {
  const racks = [1, 2].map((id) => ({ id, name: `C${id}`, u_height: 42, devices: [{ id: 10 + id, host_name: `h${id}`, position_u: 1, u_height: 1, face: 'front', status: 'active', device_type: null }] }))
  const scene = buildRowScene(racks as never)
  const box = (id: number) => scene.boxes.find((b) => b.deviceId === id)
  it('row + cabinet names with the toggle; device names only for the selected tag', () => {
    const on = labelSpecs(scene, { rowName: 'R01', names: true, side: 'front', tag: null, marker: null, box })
    expect(on.map((s) => s.text)).toEqual(['R01', 'C1', 'C2'])
    const off = labelSpecs(scene, { rowName: 'R01', names: false, side: 'front', tag: { id: 11, text: 'h1' }, marker: 11, box })
    expect(off.map((s) => [s.kind, s.text])).toEqual([['tag', 'h1'], ['marker', '◢']])
    expect(off.every((s) => s.pinned)).toBe(true)
  })
})

describe('faceOutline (selection outline)', () => {
  const b = { deviceId: 1, rackId: 1, cabIndex: 0, cx: 0, cy: 0, cz: 0, w: 1, h: 0.5, d: 0.8 } as never
  it('projects the visible face corners (wider than tall for a wide box), null when behind', () => {
    const pts = faceOutline(b, 'front', cam(6), 800, 600)!
    expect(pts).toHaveLength(4)
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y)
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(Math.max(...ys) - Math.min(...ys))
    expect((Math.max(...xs) + Math.min(...xs)) / 2).toBeCloseTo(400, 3)
    expect(faceOutline(b, 'front', cam(0.2), 800, 600)).toBeNull() // camera inside the box: rear corners behind
  })
})

describe('device tag LOD', () => {
  it('hides the tag when 1 RU is under 14 px on screen (whole-row zoom), shows it close up, with hysteresis', () => {
    const tag = A('d1', 0, { kind: 'tag', pinned: true, lod: { world: 0.04445, px: 14 } })
    expect(layoutLabels([tag], cam(2), 800, 600, new Set()).placements[0].visible).toBe(true)
    expect(layoutLabels([tag], cam(12), 800, 600, new Set()).placements[0].visible).toBe(false)
    // ~13 px: hidden if it wasn't showing, kept if it was.
    const z = 0.04445 * 2.1445 * 300 / 13 // cot(25°) ≈ 2.1445
    expect(layoutLabels([tag], cam(z), 800, 600, new Set()).placements[0].visible).toBe(false)
    expect(layoutLabels([tag], cam(z), 800, 600, new Set(['d1'])).placements[0].visible).toBe(true)
  })
})
