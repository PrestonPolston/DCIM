// Pure hall floor-plan layout (docs/design/floor-plan.md §3–5, §10).
// No React/DOM: shared by the 2D plan and a future 3D view. Output is in grid
// cells (1 cell = 1 cabinet footprint); the aisle is 2 cells deep.
// Orientation is derived on the client only and is never written back.

export type Dir = 'N' | 'E' | 'S' | 'W'
export type Aisle = 'horizontal' | 'vertical'
/** 'start' = odd rows Top (horizontal) / Left (vertical); 'end' = Bottom / Right. */
export type OddSide = 'start' | 'end'
export type Align = 'start' | 'center'

export interface HallSettings { aisle: Aisle; oddSide: OddSide; align: Align }
export const DEFAULT_SETTINGS: HallSettings = { aisle: 'horizontal', oddSide: 'start', align: 'start' }

export interface LayoutRackIn {
  id: number; name: string; u_height: number
  pos_x?: number | null; pos_y?: number | null
  effective_orientation?: Dir | null
  device_count: number; u_used: number; u_free: number
}
export interface LayoutRowIn {
  id: number; name: string
  pos_x?: number | null; pos_y?: number | null
  racks: LayoutRackIn[]
}

export type Side = 'odd' | 'even' | 'unassigned'

export interface CabinetCell {
  rack: LayoutRackIn
  rowId: number
  x: number
  y: number
  side: Side
  facing: Dir | null
  facingSource: 'api' | 'derived' | null
  /** True when the cell came from the API's pos_x/pos_y. */
  positioned: boolean
  autoPlaced: boolean
  warnings: string[]
}

export interface RowBand {
  row: LayoutRowIn
  number: number | null
  side: Side
  /** Cell coordinate of the row's start (label anchor). */
  x: number
  y: number
  warnings: string[]
}

export interface HallGeometry {
  settings: HallSettings
  cabinets: CabinetCell[]
  rows: RowBand[]
  /**
   * Aisle band: cells [start, start+size) across `axis` ('horizontal' = band runs left↔right,
   * so start is a y; 'vertical' = start is an x). Null when it can't be drawn.
   */
  aisle: { start: number; size: number; axis: Aisle } | null
  /** Unassigned strip start on the perpendicular axis, if any. */
  unassignedStart: number | null
  width: number
  height: number
  warnings: string[]
  allUnassigned: boolean
}

/** Last run of digits in the name (base 10), or null. "Row -1" → 1. */
export function rowNumber(name: string): number | null {
  const m = name.trim().match(/(\d+)(?!.*\d)/)
  return m ? parseInt(m[1], 10) : null
}

const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true })
const byNameId = <T extends { name: string; id: number }>(a: T, b: T) => natural(a.name, b.name) || a.id - b.id
const has = (v: number | null | undefined): v is number => v != null

/** Front direction for the side nearer / farther from the top (or left) of the plan. */
function sideFacing(aisle: Aisle, nearStart: boolean): Dir {
  if (aisle === 'horizontal') return nearStart ? 'S' : 'N'
  return nearStart ? 'E' : 'W'
}

export function layoutHall(rowsIn: LayoutRowIn[], settings: HallSettings = DEFAULT_SETTINGS): HallGeometry {
  const warnings: string[] = []
  const numbered = rowsIn.map((row) => ({ row, number: rowNumber(row.name) }))
  const sortRows = (a: (typeof numbered)[number], b: (typeof numbered)[number]) =>
    (a.number ?? 0) - (b.number ?? 0) || byNameId(a.row, b.row)
  const odd = numbered.filter((r) => r.number != null && r.number % 2 === 1).sort(sortRows)
  const even = numbered.filter((r) => r.number != null && r.number % 2 === 0).sort(sortRows)
  const unassigned = numbered.filter((r) => r.number == null).sort((a, b) => byNameId(a.row, b.row))

  // Duplicate row numbers
  const counts = new Map<number, number>()
  for (const r of numbered) if (r.number != null) counts.set(r.number, (counts.get(r.number) ?? 0) + 1)
  const dupWarn = (n: number | null) => (n != null && (counts.get(n) ?? 0) > 1 ? [`Duplicate row number ${n}`] : [])
  for (const [n, c] of counts) if (c > 1) warnings.push(`Duplicate row number ${n} (${c} rows)`)

  const near = settings.oddSide === 'start' ? odd : even // top / left side
  const far = settings.oddSide === 'start' ? even : odd

  // --- Positioned content (API coordinates win). p = along-aisle axis, q = perpendicular.
  const toPQ = (x: number, y: number) => (settings.aisle === 'horizontal' ? { p: x, q: y } : { p: y, q: x })
  const taken = new Set<string>()
  const key = (x: number, y: number) => `${x},${y}`
  const cabinets: CabinetCell[] = []
  const rowBands: RowBand[] = []
  let maxQ = -1

  const sideOf = (n: number | null): Side => (n == null ? 'unassigned' : n % 2 ? 'odd' : 'even')
  const facingFor = (side: Side): Dir | null =>
    side === 'unassigned' ? null : sideFacing(settings.aisle, (side === 'odd') === (settings.oddSide === 'start'))

  const pushCell = (rack: LayoutRackIn, rowId: number, x: number, y: number, side: Side, positioned: boolean, autoPlaced: boolean, extra: string[] = []) => {
    const derived = facingFor(side)
    const api = rack.effective_orientation ?? null
    const w = [...extra]
    if (api && derived && api !== derived) w.push(`faces ${api}, away from aisle`)
    cabinets.push({
      rack, rowId, x, y, side, positioned, autoPlaced, warnings: w,
      facing: api ?? derived, facingSource: api ? 'api' : derived ? 'derived' : null,
    })
    taken.add(key(x, y))
    maxQ = Math.max(maxQ, toPQ(x, y).q)
  }

  // Step B.1: fully positioned racks; B.2: their rows' remaining racks at the row origin.
  const autoRows: typeof numbered = []
  for (const r of numbered) {
    const racks = [...r.row.racks].sort(byNameId)
    const exact = racks.filter((k) => has(k.pos_x) && has(k.pos_y))
    for (const k of exact) pushCell(k, r.row.id, k.pos_x!, k.pos_y!, sideOf(r.number), true, false)
  }
  for (const r of numbered) {
    const racks = [...r.row.racks].sort(byNameId)
    const rest = racks.filter((k) => !(has(k.pos_x) && has(k.pos_y)))
    const rowPos = has(r.row.pos_x) && has(r.row.pos_y)
    if (rowPos) {
      const { p: p0, q } = toPQ(r.row.pos_x!, r.row.pos_y!)
      let p = p0
      for (const k of rest) {
        const at = () => (settings.aisle === 'horizontal' ? [p, q] : [q, p])
        while (taken.has(key(at()[0], at()[1]))) p++
        const [x, y] = at()
        const partial = has(k.pos_x) !== has(k.pos_y) ? ['Partial coordinates ignored'] : []
        pushCell(k, r.row.id, x, y, sideOf(r.number), false, false, partial)
        p++
      }
      const [x, y] = settings.aisle === 'horizontal' ? [p0, q] : [q, p0]
      rowBands.push({ row: r.row, number: r.number, side: sideOf(r.number), x, y, warnings: dupWarn(r.number) })
    } else if (rest.length || r.row.racks.length === 0) {
      autoRows.push(r)
    } else {
      // all racks exact-positioned: label at the first rack
      const first = cabinets.find((c) => c.rowId === r.row.id)!
      rowBands.push({ row: r.row, number: r.number, side: sideOf(r.number), x: first.x, y: first.y, warnings: dupWarn(r.number) })
    }
  }

  // Step A: default grid for auto rows, shifted past positioned content.
  const shift = maxQ >= 0 ? maxQ + 2 : 0
  const isAuto = (r: (typeof numbered)[number]) => autoRows.includes(r)
  const nearA = near.filter(isAuto)
  const farA = far.filter(isAuto)
  const unA = unassigned.filter(isAuto)
  const maxLen = Math.max(0, ...autoRows.map((r) => r.row.racks.length))
  const anyNumbered = odd.length + even.length > 0

  const qRows: { r: (typeof numbered)[number]; q: number }[] = []
  nearA.forEach((r, i) => qRows.push({ r, q: 2 * (nearA.length - 1 - i) }))
  const aisleQ = anyNumbered ? (nearA.length ? 2 * nearA.length - 1 : 0) : null
  let lastQ = aisleQ != null ? aisleQ + 1 : -1
  farA.forEach((r, i) => {
    const q = (aisleQ ?? 0) + 2 + 2 * i
    qRows.push({ r, q })
    lastQ = q
  })
  const unStart = unA.length ? (anyNumbered ? lastQ + 3 : 0) : null
  unA.forEach((r, i) => qRows.push({ r, q: unStart! + 2 * i }))

  for (const { r, q: q0 } of qRows) {
    const q = q0 + shift
    const racks = [...r.row.racks].sort(byNameId)
    const offset = settings.align === 'center' ? Math.floor((maxLen - racks.length) / 2) : 0
    let p = offset
    const side = sideOf(r.number)
    for (const k of racks) {
      const at = () => (settings.aisle === 'horizontal' ? [p, q] : [q, p])
      while (taken.has(key(at()[0], at()[1]))) p++
      const [x, y] = at()
      const partial = has(k.pos_x) !== has(k.pos_y) ? ['Partial coordinates ignored'] : []
      pushCell(k, r.row.id, x, y, side, false, true, partial)
      p++
    }
    const [x, y] = settings.aisle === 'horizontal' ? [offset, q] : [q, offset]
    const w = dupWarn(r.number)
    if (racks.length === 0) w.push('no cabinets')
    rowBands.push({ row: r.row, number: r.number, side, x, y, warnings: w })
  }

  const maxX = Math.max(-1, ...cabinets.map((c) => c.x), ...rowBands.map((b) => b.x))
  const maxY = Math.max(-1, ...cabinets.map((c) => c.y), ...rowBands.map((b) => b.y))
  let aisle: HallGeometry['aisle'] =
    aisleQ != null && autoRows.some((r) => r.number != null) ? { start: aisleQ + shift, size: 2, axis: settings.aisle } : null
  if (!aisle) aisle = detectPositionedAisle(cabinets)
  const perpExtent = Math.max(settings.aisle === 'horizontal' ? maxY + 1 : maxX + 1, aisle && aisle.axis === settings.aisle ? aisle.start + aisle.size : 0)
  const alongExtent = settings.aisle === 'horizontal' ? maxX + 1 : maxY + 1
  if (!anyNumbered && rowsIn.length) warnings.push('Add numbers to row names to lay out the hall')

  return {
    settings,
    cabinets,
    rows: rowBands,
    aisle,
    unassignedStart: unStart != null ? unStart + shift : null,
    width: settings.aisle === 'horizontal' ? Math.max(alongExtent, 1) : perpExtent,
    height: settings.aisle === 'horizontal' ? perpExtent : Math.max(alongExtent, 1),
    warnings,
    allUnassigned: !anyNumbered && rowsIn.length > 0,
  }
}

/** For API-positioned halls: if odd and even cabinets are separated by an empty band, that band is the aisle. */
function detectPositionedAisle(cells: CabinetCell[]): HallGeometry['aisle'] {
  const odd = cells.filter((c) => c.side === 'odd')
  const even = cells.filter((c) => c.side === 'even')
  if (!odd.length || !even.length) return null
  for (const axis of ['vertical', 'horizontal'] as const) {
    const v = (c: CabinetCell) => (axis === 'vertical' ? c.x : c.y)
    const oMin = Math.min(...odd.map(v)), oMax = Math.max(...odd.map(v))
    const eMin = Math.min(...even.map(v)), eMax = Math.max(...even.map(v))
    if (oMax < eMin - 1) return { start: oMax + 1, size: eMin - oMax - 1, axis }
    if (eMax < oMin - 1) return { start: eMax + 1, size: oMin - eMax - 1, axis }
  }
  return null
}
