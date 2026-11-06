import { memo } from 'react'
import { Link } from 'react-router'
import { rackU, splitCabinetName } from '../../lib/rack'
import type { CabinetCell, Dir, HallGeometry } from '../../lib/hallLayout'

const ARROW: Record<Dir, string> = { N: '▲', E: '▶', S: '▼', W: '◀' }

const Tile = memo(function Tile({ cell, hallId, horizontal, selected }: { cell: CabinetCell; hallId: number; horizontal: boolean; selected: boolean }) {
  const c = cell.rack
  const u = rackU(c)
  const pct = Math.round((c.u_used / u) * 100)
  const facing = cell.facing
    ? `front faces ${cell.facing}${cell.facingSource === 'derived' ? ` (default for ${cell.side} rows)` : ''}`
    : 'Front direction not set'
  const nm = splitCabinetName(c.name)
  const warn = cell.warnings.length ? ` ⚠ ${cell.warnings.join('; ')}` : ''
  return (
    <Link
      to={`/halls/${hallId}/cabinets/${c.id}`}
      className={`cabinet-tile${c.device_count === 0 ? ' empty' : ''}${selected ? ' selected' : ''}${cell.facing ? ` front-${cell.facing}` : ''}`}
      style={horizontal ? { gridColumn: cell.x + 2, gridRow: cell.y + 1 } : { gridColumn: cell.x + 1, gridRow: cell.y + 2 }}
      aria-label={`Cabinet ${c.name}, ${c.u_used} of ${u} RU used, ${c.u_free} free, ${facing}`}
      title={`${c.name}: ${c.u_used}/${u} RU used · ${c.u_free} free · ${c.device_count} devices · ${facing}${warn}`}
    >
      <span className="tile-name">{nm.prefix && <span className="tile-prefix" aria-hidden="true">{nm.prefix}</span>}{nm.short}{warn && <span aria-hidden="true"> ⚠</span>}</span>
      <span className="utilbar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
      {cell.facing && <span className="tile-arrow" aria-hidden="true">{ARROW[cell.facing]}</span>}
    </Link>
  )
})

/**
 * 2D hall plan rendered from layoutHall() geometry with one CSS grid:
 * the along-aisle axis is uniform tiles; the perpendicular axis has tile,
 * back-of-row gap and aisle tracks. Row labels are sticky.
 */
export default function FloorPlan({ hallId, geometry, selectedId }: { hallId: number; geometry: HallGeometry; selectedId?: number }) {
  const g = geometry
  const horizontal = g.settings.aisle === 'horizontal'
  const along = horizontal ? g.width : g.height
  const perp = horizontal ? g.height : g.width
  const occupied = new Set<number>()
  for (const c of g.cabinets) occupied.add(horizontal ? c.y : c.x)
  for (const r of g.rows) occupied.add(horizontal ? r.y : r.x)
  const aisleOnPerp = g.aisle && g.aisle.axis === g.settings.aisle ? g.aisle : null
  const tracks = Array.from({ length: perp }, (_, q) =>
    aisleOnPerp && q >= aisleOnPerp.start && q < aisleOnPerp.start + aisleOnPerp.size
      ? 'var(--aisle-cell)'
      : g.unassignedStart != null && q === g.unassignedStart - 1
        ? '28px'
        : occupied.has(q) ? 'var(--tile)' : 'var(--row-gap)',
  ).join(' ')
  const alongTracks = `repeat(${Math.max(along, 1)}, var(--tile))`
  const style = horizontal
    ? { gridTemplateColumns: `var(--label-w) ${alongTracks}`, gridTemplateRows: tracks }
    : { gridTemplateColumns: tracks, gridTemplateRows: `var(--label-h) ${alongTracks}` }
  const perpSpan = (q: number, n = 1) =>
    horizontal ? { gridRow: `${q + 1} / span ${n}`, gridColumn: '1 / -1' } : { gridColumn: `${q + 1} / span ${n}`, gridRow: '1 / -1' }

  // Rows sharing a line (e.g. both banks of a positioned hall) share one pinned label.
  const byLine = new Map<number, HallGeometry['rows']>()
  for (const r of g.rows) {
    const line = horizontal ? r.y : r.x
    byLine.set(line, [...(byLine.get(line) ?? []), r])
  }
  const labels = [...byLine].map(([line, rows]) => ({ line, rows }))

  if (g.cabinets.length === 0 && g.rows.length === 0) return <p className="hint">No rows in this hall yet.</p>
  return (
    <div className={`floorplan ${horizontal ? 'fp-h' : 'fp-v'}`} style={style} role="group" aria-label="Hall floor plan">
      {g.aisle && (
        <div
          className={`fp-aisle${g.aisle.axis === 'vertical' ? ' vertical' : ''}`}
          style={
            aisleOnPerp
              ? perpSpan(g.aisle.start, g.aisle.size)
              : horizontal // aisle runs across the other axis (API-positioned hall)
                ? { gridColumn: `${g.aisle.start + 2} / span ${g.aisle.size}`, gridRow: '1 / -1' }
                : { gridRow: `${g.aisle.start + 2} / span ${g.aisle.size}`, gridColumn: '1 / -1' }
          }
          aria-label="Center aisle"
        >
          <span>CENTER AISLE · fronts face here</span>
        </div>
      )}
      {g.unassignedStart != null && (
        <div className="fp-unassigned" style={perpSpan(g.unassignedStart - 1)} title="Rename the row to include its number, for example 'Row 7'.">
          Unassigned rows: no row number in name
        </div>
      )}
      {labels.map(({ line, rows: rs }) => {
        const warns = rs.flatMap((r) => r.warnings.map((w) => `${r.row.name}: ${w}`))
        return (
          <div
            key={line}
            className={`fp-label${warns.length ? ' warn' : ''}`}
            style={horizontal ? { gridColumn: 1, gridRow: line + 1 } : { gridRow: 1, gridColumn: line + 1 }}
            title={warns.join('; ') || undefined}
          >
            {rs.map((r, i) => (
              <span key={r.row.id}>{i > 0 && ' · '}<Link to={`/halls/${hallId}/rows/${r.row.id}`} className="fp-row-link">{r.row.name}</Link></span>
            ))}
            {warns.length > 0 && <span className="visually-hidden">: {warns.join('; ')}</span>}
            {warns.length > 0 && <span aria-hidden="true"> ⚠</span>}
          </div>
        )
      })}
      {g.cabinets.map((c) => (
        <Tile key={c.rack.id} cell={c} hallId={hallId} horizontal={horizontal} selected={c.rack.id === selectedId} />
      ))}
    </div>
  )
}
