import { describe, expect, it } from 'vitest'
import type { RowFrontDevice, RowFrontRack } from './rowFront'
import {
  buildRowScene, CAB_W, deviceDepth, faceKey, flipPose, FULL_D, groupBoxes, HALF_D, navigate, orbitPose,
  presetPose, RAIL_F, RAIL_R, RU_M, sideOf,
} from './row3d'
import { LruCache, textureBytes } from './lru'

const img = (n: string) => ({ url: `/i/${n}`, thumb_url: `/i/${n}?variant=thumb` })
function dev(p: Partial<RowFrontDevice> & { id: number; position_u: number }): RowFrontDevice {
  return {
    host_name: `h${p.id}`, status: 'active', serial_number: null, top_u: p.position_u, face: 'front',
    device_type: { id: 1, manufacturer: 'M', name: 'T', u_height: 1, is_full_depth: true, asset_type: 'server' }, ...p,
  }
}
const rack = (id: number, devices: RowFrontDevice[]): RowFrontRack => ({
  id, name: `R${id}`, u_height: 53, pos_x: id, pos_y: 0, effective_orientation: 'S', u_used: 0, u_free: 53, devices,
})

describe('row3d scene', () => {
  it('lays cabinets left→right centred on x=0 and stacks devices by RU', () => {
    const s = buildRowScene([rack(1, [dev({ id: 1, position_u: 1, top_u: 2 })]), rack(2, [])])
    expect(s.width).toBeCloseTo(2 * CAB_W)
    expect(s.cabinets.map((c) => c.x)).toEqual([-0.3, 0.3])
    const b = s.boxes[0]
    expect(b.h).toBeCloseTo(2 * RU_M - 0.002)
    expect(b.cy).toBeCloseTo(0.1 + RU_M)
    expect(b.cz).toBeCloseTo(RAIL_F - FULL_D / 2)
  })
  it('half depth, depth_mm, blanks and rear-mounted devices', () => {
    expect(deviceDepth(dev({ id: 1, position_u: 1, is_full_depth: false }))).toBe(HALF_D)
    expect(deviceDepth(dev({ id: 1, position_u: 1, is_full_depth: false, depth_mm: 300 }))).toBeCloseTo(0.3)
    expect(deviceDepth(dev({ id: 1, position_u: 1, is_full_depth: true, depth_mm: 300 }))).toBe(FULL_D) // spans the rails
    expect(deviceDepth(dev({ id: 1, position_u: 1, effective_asset_type: 'blank' }))).toBeCloseTo(0.02)
    const s = buildRowScene([rack(1, [dev({ id: 9, position_u: 5, face: 'rear', is_full_depth: false, effective_front_image: img('f'), effective_rear_image: img('r') })])])
    const b = s.boxes[0]
    expect(b.cz).toBeCloseTo(RAIL_R + HALF_D / 2)
    expect(b.plusZ).toBe('/i/r?variant=thumb') // its rear faces the aisle
    expect(b.minusZ).toBe('/i/f?variant=thumb')
  })
  it('falls back to generic art per asset type and face; cable managers have no rear photo', () => {
    expect(faceKey(dev({ id: 1, position_u: 1, effective_front_image: img('f') }), 'rear')).toBe('generic:rear:server')
    expect(faceKey(dev({ id: 1, position_u: 1, effective_asset_type: 'cable_manager', effective_rear_image: img('r') }), 'rear')).toBe('generic:rear:cable_manager')
  })
  it('groups instances by their pair of face textures (dedupe by profile image)', () => {
    const a = { effective_front_image: img('a'), effective_rear_image: img('ar') }
    const s = buildRowScene([rack(1, [dev({ id: 1, position_u: 1, ...a }), dev({ id: 2, position_u: 3, ...a }), dev({ id: 3, position_u: 5 })])])
    const g = groupBoxes(s.boxes)
    expect(g.size).toBe(2)
    expect([...g.values()].map((l) => l.length).sort()).toEqual([1, 2])
  })
})

describe('row3d camera', () => {
  const s = buildRowScene([rack(1, []), rack(2, []), rack(3, [])])
  it('front/rear presets sit on opposite sides; flip is a 180° orbit about the target', () => {
    const f = presetPose('front', s, 16 / 9)
    expect(sideOf(f)).toBe('front')
    expect(sideOf(presetPose('rear', s, 16 / 9))).toBe('rear')
    const r = flipPose(f)
    expect(sideOf(r)).toBe('rear')
    expect(r.position[2]).toBeCloseTo(-f.position[2])
    const mid = orbitPose(f, 0.5)
    const d0 = Math.hypot(f.position[0] - f.target[0], f.position[2] - f.target[2])
    expect(Math.hypot(mid.position[0] - f.target[0], mid.position[2] - f.target[2])).toBeCloseTo(d0) // stays on the circle
    expect(orbitPose(f, 1).position[2]).toBeCloseTo(-f.position[2])
  })
})

describe('row3d keyboard navigation', () => {
  const racks = [
    rack(1, [dev({ id: 1, position_u: 1 }), dev({ id: 2, position_u: 10 })]),
    rack(2, []),
    rack(3, [dev({ id: 3, position_u: 2 }), dev({ id: 4, position_u: 30 })]),
  ]
  it('moves within and across cabinets (skipping empty ones), mirrored from the rear', () => {
    expect(navigate(racks, null, 'ArrowUp')).toBe(1)
    expect(navigate(racks, 1, 'ArrowUp')).toBe(2)
    expect(navigate(racks, 2, 'ArrowUp')).toBe(2)
    expect(navigate(racks, 2, 'ArrowDown')).toBe(1)
    expect(navigate(racks, 2, 'ArrowRight')).toBe(3)
    expect(navigate(racks, 3, 'ArrowLeft')).toBe(1) // nearest RU
    expect(navigate(racks, 2, 'ArrowLeft', 'rear')).toBe(3)
  })
})

describe('LruCache', () => {
  it('evicts least recently used by count and by bytes', () => {
    const out: string[] = []
    const c = new LruCache<number>(2, 100, (k) => out.push(k))
    c.set('a', 1, 10); c.set('b', 2, 10); c.get('a'); c.set('c', 3, 10)
    expect(out).toEqual(['b'])
    c.set('d', 4, 95)
    expect(out).toEqual(['b', 'a', 'c'])
    expect(c.size).toBe(1)
    expect(c.bytes).toBe(95)
    expect(textureBytes(1024, 189)).toBe(Math.round(1024 * 189 * 4 * 4 / 3))
  })
})

describe('close-up textures (tex variant)', () => {
  it('prefers tex_url, falls back to the original; neighbours of the focused cabinet', async () => {
    const { closeUpUrl, closeUpCabinets } = await import('./row3d')
    expect(closeUpUrl({ url: '/o', tex_url: '/t' })).toBe('/t')
    expect(closeUpUrl({ url: '/o' })).toBe('/o')
    expect(closeUpCabinets(0, 3)).toEqual([0, 1])
    expect(closeUpCabinets(2, 3)).toEqual([2, 1])
    const s = buildRowScene([rack(1, [dev({ id: 1, position_u: 1, effective_front_image: { url: '/o', thumb_url: '/th', tex_url: '/tx' } })])])
    expect(s.full['/th']).toBe('/tx')
  })
})

describe('half-depth devices draw at their true depth', () => {
  it('uses depth_mm from the mounting rail; full depth ignores depth_mm (rail to rail)', () => {
    const s = buildRowScene([rack(1, [
      dev({ id: 1, position_u: 1, is_full_depth: false, depth_mm: 300, mounting: 'shelf' }),
      dev({ id: 2, position_u: 3, is_full_depth: false, depth_mm: 250, face: 'rear' }),
      dev({ id: 3, position_u: 5, is_full_depth: true, depth_mm: 300 }),
      dev({ id: 4, position_u: 7, is_full_depth: false, depth_mm: 5000 }),
    ])])
    const b = (id: number) => s.boxes.find((x) => x.deviceId === id)!
    expect(b(1).d).toBeCloseTo(0.3); expect(b(1).cz + b(1).d / 2).toBeCloseTo(RAIL_F) // front rail → back
    expect(b(2).d).toBeCloseTo(0.25); expect(b(2).cz - b(2).d / 2).toBeCloseTo(RAIL_R) // rear rail → forward
    expect(b(3).d).toBe(FULL_D)
    expect(b(4).d).toBe(FULL_D) // capped
  })
})
