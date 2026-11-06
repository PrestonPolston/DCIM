import { describe, expect, it } from 'vitest'
import { DEFAULT_SETTINGS } from './hallLayout'
import {
  buildColumn, cabinetOrder, categoryOf, detailCw, deviceAria, deviceCategory, fitCw, fitRu, lod, navigate,
  rowFacing, rowHeightU, rowSummary, rulerLabels, settingsFromHint, zoomStep, type RowFrontDevice, type RowFrontRack,
} from './rowFront'

const rack = (id: number, name: string, extra: Partial<RowFrontRack> = {}): RowFrontRack => ({
  id, name, u_height: 53, pos_x: null, pos_y: null, effective_orientation: null, u_used: 0, u_free: 53, devices: [], ...extra,
})
const dev = (p: Partial<RowFrontDevice>): RowFrontDevice => ({
  id: 1, host_name: 'd', status: 'active', serial_number: 'S', position_u: 1, top_u: 1, face: 'front',
  device_type: { id: 1, manufacturer: 'Dell', name: 'R660 server', u_height: 1, is_full_depth: true }, ...p,
})
const names = (r: { name: string }[]) => r.map((x) => x.name)
const row14 = Array.from({ length: 14 }, (_, i) => rack(i + 1, `C${String(14 - i).padStart(2, '0')}`))

describe('cabinetOrder (§7)', () => {
  it('S (odd row, horizontal aisle): C01..C14 by name when unpositioned; rear reversed', () => {
    const o = cabinetOrder(row14, 'S', 'front')
    expect(names(o.racks)[0]).toBe('C01')
    expect(names(o.racks)[13]).toBe('C14')
    expect([o.left, o.right]).toEqual(['W', 'E'])
    const r = cabinetOrder(row14, 'S', 'rear')
    expect(names(r.racks)[0]).toBe('C14')
    expect([r.left, r.right]).toEqual(['E', 'W'])
  })
  it('N (even row): C14..C01', () => {
    expect(names(cabinetOrder(row14, 'N', 'front').racks).slice(0, 2)).toEqual(['C14', 'C13'])
    expect(names(cabinetOrder(row14, 'N', 'rear').racks)[0]).toBe('C01')
  })
  it('uses pos_x for N/S and pos_y for E/W when every cabinet has it', () => {
    const rs = [rack(1, 'A', { pos_x: 3, pos_y: 1 }), rack(2, 'B', { pos_x: 1, pos_y: 9 }), rack(3, 'C', { pos_x: 2, pos_y: 5 })]
    expect(names(cabinetOrder(rs, 'S', 'front').racks)).toEqual(['B', 'C', 'A'])
    expect(names(cabinetOrder(rs, 'N', 'front').racks)).toEqual(['A', 'C', 'B'])
    expect(names(cabinetOrder(rs, 'E', 'front').racks)).toEqual(['B', 'C', 'A']) // descending y
    expect(names(cabinetOrder(rs, 'W', 'front').racks)).toEqual(['A', 'C', 'B']) // ascending y
    expect(names(cabinetOrder(rs, 'W', 'rear').racks)).toEqual(['B', 'C', 'A'])
    expect(cabinetOrder(rs, 'E', 'front')).toMatchObject({ left: 'S', right: 'N' })
  })
  it('unknown facing: natural name order with a note; rear reversed', () => {
    const o = cabinetOrder([rack(1, 'C10'), rack(2, 'C2'), rack(3, 'C1')], null, 'front')
    expect(names(o.racks)).toEqual(['C1', 'C2', 'C10'])
    expect(o.note).toBe('Facing not set')
    expect(names(cabinetOrder([rack(1, 'C10'), rack(2, 'C2')], null, 'rear').racks)).toEqual(['C10', 'C2'])
  })
})

describe('facing via lib/hallLayout', () => {
  const rows = [3, 4].map((n) => ({ id: n, name: `Row ${n}`, racks: [{ id: n * 10, name: 'C01', u_height: 53, device_count: 0, u_used: 0, u_free: 53 }] }))
  it('derives S for odd and N for even rows by default; API hint vertical → E/W', () => {
    expect(rowFacing(rows, 3, DEFAULT_SETTINGS)).toBe('S')
    expect(rowFacing(rows, 4, DEFAULT_SETTINGS)).toBe('N')
    const v = settingsFromHint({ id: 1, name: 'H', aisle_axis: 'y', odd_side: 'low' }, null, DEFAULT_SETTINGS)
    expect(v).toMatchObject({ aisle: 'vertical', oddSide: 'start' })
    expect(rowFacing(rows, 3, v)).toBe('E')
  })
})

describe('scale and LOD (§1, §2)', () => {
  it('fit ru = clamp(6, floor(availH/53), 12)', () => {
    expect(fitRu(724)).toBe(12)
    expect(fitRu(592)).toBe(11)
    expect(fitRu(200)).toBe(6)
    expect(fitRu(5000)).toBe(12)
  })
  it('fit cw matches the spec table: 14 cabinets fit on desktop and tablet', () => {
    expect(fitCw(1160, 14, 40, 8)).toBe(72)
    expect(fitCw(800, 14, 40, 6)).toBe(48)
    expect(fitCw(1024, 14, 32, 6)).toBe(65)
    expect(fitCw(390, 14, 24, 2)).toBe(24)
    expect(detailCw(24)).toBe(240)
  })
  it('LOD thresholds and zoom steps', () => {
    expect([lod(6), lod(9), lod(10), lod(19), lod(20), lod(48)]).toEqual([0, 0, 1, 1, 2, 2])
    expect(zoomStep(12, 1)).toBe(16)
    expect(zoomStep(11, -1)).toBe(8)
    expect(zoomStep(48, 1)).toBe(48)
    expect(rulerLabels(53)).toEqual([1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 53])
  })
})

describe('categories (§5)', () => {
  it('keywords, other, unknown', () => {
    expect(categoryOf('GPU node')).toBe('server')
    expect(categoryOf('Core Router')).toBe('switch')
    expect(categoryOf('MPO cassette')).toBe('patch')
    expect(categoryOf('ATS')).toBe('pdu')
    expect(categoryOf('whatever')).toBe('other')
    expect(deviceCategory(dev({ device_type: null }))).toBe('unknown')
    expect(deviceCategory(dev({ effective_asset_type: 'switch' }))).toBe('switch')
  })
})

describe('columns: mixed 53U / 42U, no collapse, keyboard nav', () => {
  const a = rack(1, 'A', { devices: [dev({ id: 1, host_name: 'web-01', position_u: 20, device_type: { id: 1, manufacturer: 'Dell', name: 'R660', u_height: 2, is_full_depth: true } })] })
  const b = rack(2, 'B', { u_height: 42, devices: [dev({ id: 2, host_name: 'sw', position_u: 21, face: 'rear', device_type: { id: 2, manufacturer: 'A', name: 'sw', u_height: 1, is_full_depth: false } })] })
  const cols = [buildColumn(a, 'front'), buildColumn(b, 'front')]
  it('each column uses its own u_height and keeps every empty RU (runs, not collapsed)', () => {
    expect(rowHeightU([a, b])).toBe(53)
    expect(cols[0].items.map((i) => [i.kind, i.top, i.bottom])).toEqual([['empty', 53, 22], ['device', 21, 20], ['empty', 19, 1]])
    expect(cols[1].u).toBe(42)
    expect(cols[1].items).toEqual([{ kind: 'empty', top: 42, bottom: 1 }])
    expect(cols[1].behind.map((d) => d.host_name)).toEqual(['sw'])
    expect(buildColumn(b, 'rear').items.some((i) => i.kind === 'device')).toBe(true)
    // Full-depth front device shows as pass-through on the rear
    expect(buildColumn(a, 'rear').items.find((i) => i.kind === 'device')).toMatchObject({ passThrough: true })
  })
  it('navigate: ↑/↓ within cabinet, ←/→ same RU (clamped to the 42U cabinet), PgUp/PgDn, Home/End', () => {
    expect(navigate(cols, { col: 0, u: 21 }, 'ArrowUp')).toEqual({ col: 0, u: 53 })
    expect(navigate(cols, { col: 0, u: 21 }, 'ArrowDown')).toEqual({ col: 0, u: 19 })
    expect(navigate(cols, { col: 0, u: 21 }, 'ArrowRight')).toEqual({ col: 1, u: 42 })
    expect(navigate(cols, { col: 1, u: 42 }, 'ArrowLeft')).toEqual({ col: 0, u: 53 })
    expect(navigate(cols, { col: 0, u: 19 }, 'PageUp')).toEqual({ col: 0, u: 53 })
    expect(navigate(cols, { col: 0, u: 15 }, 'PageUp')).toEqual({ col: 0, u: 53 })
    expect(navigate(cols, { col: 0, u: 53 }, 'PageDown')).toEqual({ col: 0, u: 53 })
    expect(navigate(cols, { col: 0, u: 21 }, 'End')).toEqual({ col: 1, u: 42 })
    expect(navigate(cols, { col: 0, u: 21 }, 'x')).toBeNull()
  })
  it('summary and aria label', () => {
    const s = rowSummary([{ ...a, u_used: 2 }, { ...b, u_used: 1 }])
    expect([s.used, s.total, s.status.get('active')]).toEqual([3, 95, 2])
    expect(deviceAria(a.devices[0], 'A', false)).toBe('web-01, Active, cabinet A, RU 20 to 21, front')
    expect(deviceAria(dev({ serial_number: null }), 'A', false)).toContain('no serial')
  })
})

describe('cable_manager (11th asset type)', () => {
  it('maps to its own generic front category', async () => {
    const { categoryOf, CATEGORY_LABEL } = await import('./rowFront')
    expect(categoryOf('cable_manager')).toBe('cable')
    expect(CATEGORY_LABEL.cable).toBe('CABLE MANAGER')
    expect(categoryOf('patch_panel')).toBe('patch')
  })
})
