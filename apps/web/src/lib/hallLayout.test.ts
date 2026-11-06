import { describe, expect, it } from 'vitest'
import { layoutHall, rowNumber, type LayoutRowIn } from './hallLayout'
import { splitCabinetName } from './rack'

let nextId = 1
const rack = (name: string, extra = {}) => ({ id: nextId++, name, u_height: 53, device_count: 0, u_used: 0, u_free: 53, ...extra })
const row = (name: string, n = 2, extra = {}): LayoutRowIn => ({
  id: nextId++, name, racks: Array.from({ length: n }, (_, i) => rack(`${name}-C${i + 1}`)), ...extra,
})
const cellsOf = (g: ReturnType<typeof layoutHall>, rowName: string) =>
  g.cabinets.filter((c) => g.rows.find((r) => r.row.id === c.rowId)!.row.name === rowName)

describe('rowNumber', () => {
  it.each([
    ['Row 1', 1], ['R03', 3], ['A-12', 12], ['Hall2 Row5', 5], ['12B', 12], ['Row 0', 0], ['Row -1', 1], ['Spare', null], ['Network row', null],
  ])('%s → %s', (name, n) => expect(rowNumber(name)).toBe(n))
})

describe('layoutHall (horizontal aisle, odd on top)', () => {
  const g = layoutHall([row('Row 2'), row('Row 1'), row('Row 3'), row('Row 4')])
  it('puts odd rows above the aisle (nearest first) and even rows below', () => {
    expect(g.aisle).toEqual({ start: 3, size: 2, axis: 'horizontal' })
    expect(cellsOf(g, 'Row 1').map((c) => c.y)).toEqual([2, 2])
    expect(cellsOf(g, 'Row 3')[0].y).toBe(0)
    expect(cellsOf(g, 'Row 2')[0].y).toBe(5)
    expect(cellsOf(g, 'Row 4')[0].y).toBe(7)
    expect(cellsOf(g, 'Row 1').map((c) => c.x)).toEqual([0, 1])
  })
  it('derives facing toward the aisle: odd S, even N', () => {
    expect(cellsOf(g, 'Row 1')[0]).toMatchObject({ facing: 'S', facingSource: 'derived' })
    expect(cellsOf(g, 'Row 2')[0]).toMatchObject({ facing: 'N', facingSource: 'derived' })
  })
})

describe('facing table', () => {
  it.each([
    ['horizontal', 'start', 'S', 'N'],
    ['horizontal', 'end', 'N', 'S'],
    ['vertical', 'start', 'E', 'W'],
    ['vertical', 'end', 'W', 'E'],
  ] as const)('%s aisle, odd %s → odd %s, even %s', (aisle, oddSide, oddF, evenF) => {
    const g = layoutHall([row('Row 1'), row('Row 2')], { aisle, oddSide, align: 'start' })
    expect(cellsOf(g, 'Row 1')[0].facing).toBe(oddF)
    expect(cellsOf(g, 'Row 2')[0].facing).toBe(evenF)
  })
  it('vertical aisle swaps axes', () => {
    const g = layoutHall([row('Row 1'), row('Row 2')], { aisle: 'vertical', oddSide: 'start', align: 'start' })
    expect(cellsOf(g, 'Row 1').map((c) => [c.x, c.y])).toEqual([[0, 0], [0, 1]])
    expect(cellsOf(g, 'Row 2')[0].x).toBe(3)
  })
})

describe('edge cases', () => {
  it('unnumbered rows go in the Unassigned strip with no facing', () => {
    const g = layoutHall([row('Row 1'), row('Spare')])
    const spare = cellsOf(g, 'Spare')
    expect(spare[0]).toMatchObject({ side: 'unassigned', facing: null })
    expect(g.unassignedStart).toBe(spare[0].y)
    expect(spare[0].y).toBeGreaterThan(g.aisle!.start + 1)
  })
  it('all rows unassigned: no aisle, warning', () => {
    const g = layoutHall([row('Spare'), row('Lab')])
    expect(g.aisle).toBeNull()
    expect(g.allUnassigned).toBe(true)
    expect(g.warnings).toContain('Add numbers to row names to lay out the hall')
  })
  it('duplicate row numbers warn and stay side by side', () => {
    const g = layoutHall([row('Row 3'), row('R03')])
    expect(g.warnings[0]).toMatch(/Duplicate row number 3/)
    expect(g.rows.every((r) => r.warnings.includes('Duplicate row number 3'))).toBe(true)
    expect(g.rows.every((r) => r.side === 'odd')).toBe(true)
  })
  it('a single row still draws the aisle', () => {
    const g = layoutHall([row('Row 1')])
    expect(g.aisle).toEqual({ start: 1, size: 2, axis: 'horizontal' })
    expect(g.height).toBe(3)
  })
  it('a single even row draws the aisle above it', () => {
    const g = layoutHall([row('Row 2')])
    expect(g.aisle).toEqual({ start: 0, size: 2, axis: 'horizontal' })
    expect(cellsOf(g, 'Row 2')[0].y).toBe(2)
  })
  it('odd count of rows (1–5) keeps uneven sides', () => {
    const g = layoutHall(['Row 1', 'Row 2', 'Row 3', 'Row 4', 'Row 5'].map((n) => row(n, 1)))
    expect(g.aisle!.start).toBe(5)
    expect(cellsOf(g, 'Row 5')[0].y).toBe(0)
    expect(cellsOf(g, 'Row 4')[0].y).toBe(9)
  })
  it('API orientation and coordinates win; disagreement warns', () => {
    const r1 = row('Row 1', 0)
    r1.racks = [rack('A', { pos_x: 5, pos_y: 9, effective_orientation: 'N' }), rack('B', { pos_x: 3 })]
    const g = layoutHall([r1])
    const a = g.cabinets.find((c) => c.rack.name === 'A')!
    expect(a).toMatchObject({ x: 5, y: 9, positioned: true, facing: 'N', facingSource: 'api' })
    expect(a.warnings).toContain('faces N, away from aisle')
    const b = g.cabinets.find((c) => c.rack.name === 'B')!
    expect(b.warnings).toContain('Partial coordinates ignored')
    expect(b.y).toBeGreaterThanOrEqual(11) // auto grid shifted past positioned content
  })
  it('detects the aisle between positioned odd and even banks (seed_demo shape)', () => {
    const mk = (name: string, xs: number[], y: number, o: 'E' | 'W'): LayoutRowIn => ({
      id: nextId++, name, pos_x: xs[0], pos_y: y, racks: xs.map((x, j) => rack(`${name}-C${j}`, { pos_x: x, pos_y: y, effective_orientation: o })),
    })
    const g = layoutHall([mk('R01', [13, 12], 0, 'E'), mk('R02', [17, 18], 0, 'W'), mk('R03', [13, 12], 2, 'E')])
    expect(g.aisle).toEqual({ start: 14, size: 3, axis: 'vertical' })
    expect(g.cabinets.every((c) => c.positioned && c.facingSource === 'api')).toBe(true)
  })
  it('row with no cabinets keeps its slot', () => {
    const g = layoutHall([row('Row 1'), row('Row 3', 0)])
    expect(g.rows.find((r) => r.row.name === 'Row 3')!.warnings).toContain('no cabinets')
  })
  it('handles 420 cabinets quickly', () => {
    const rows = Array.from({ length: 20 }, (_, i) => row(`Row ${i + 1}`, 21))
    const t = performance.now()
    const g = layoutHall(rows)
    expect(g.cabinets).toHaveLength(420)
    expect(performance.now() - t).toBeLessThan(100)
    expect(new Set(g.cabinets.map((c) => `${c.x},${c.y}`)).size).toBe(420)
  })
})

describe('splitCabinetName', () => {
  it('keeps the part after the row prefix', () => {
    expect(splitCabinetName('R01-C14')).toEqual({ prefix: 'R01-', short: 'C14' })
    expect(splitCabinetName('C304')).toEqual({ prefix: '', short: 'C304' })
    expect(splitCabinetName('DH2 R3 C05')).toEqual({ prefix: 'DH2 R3 ', short: 'C05' })
  })
})
