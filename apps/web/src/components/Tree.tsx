import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useHallLayout, useHalls, useRackElevation } from '../api/racks'
import type { HallLayoutRack, HallLayoutRow } from '../api/types'
import { rackU } from '../lib/rack'
import { statusClass, statusIcon, statusLabel } from '../lib/status'
import { sortRows, sortCabinets } from './floorplan/order'

// Navigation tree: Data Hall › Row › Cabinet › RU › Device (docs/design/screens.md).
// Levels load lazily: /halls, /halls/{id}/layout, /racks/{id}/elevation.

function Toggle({ open, onClick, label }: { open: boolean; onClick: () => void; label: string }) {
  return (
    <button type="button" className="ghost icon tree-toggle" aria-label={`${open ? 'Collapse' : 'Expand'} ${label}`} onClick={onClick}>
      {open ? '▾' : '▸'}
    </button>
  )
}

function CabinetNode({ hallId, rack, selected }: { hallId: number; rack: HallLayoutRack; selected: boolean }) {
  const [open, setOpen] = useState(selected)
  const { data } = useRackElevation(rack.id, open)
  return (
    <li role="treeitem" aria-expanded={open} aria-selected={selected}>
      <div className="tree-row">
        <Toggle open={open} onClick={() => setOpen(!open)} label={rack.name} />
        <Link to={`/halls/${hallId}/cabinets/${rack.id}`} className={selected ? 'tree-link active' : 'tree-link'}>
          {rack.name} <span className="hint mono">{rack.u_used}/{rackU(rack)}</span>
        </Link>
      </div>
      {open && (
        <ul role="group">
          {!data ? (
            <li className="tree-row hint">Loading…</li>
          ) : data.devices.length === 0 ? (
            <li className="tree-row hint">Empty</li>
          ) : (
            data.devices.map((d) => (
              <li key={d.id} role="treeitem" className="tree-row tree-leaf">
                <span className="mono hint">RU {d.position_u === d.top_u ? d.position_u : `${d.position_u}–${d.top_u}`}</span>
                <span className={`tree-status ${statusClass(d.status)}`} aria-label={statusLabel(d.status)}>{statusIcon(d.status)}</span>
                <Link className="mono" to={`/halls/${hallId}/cabinets/${rack.id}?device=${d.id}`}>{d.host_name}</Link>
              </li>
            ))
          )}
        </ul>
      )}
    </li>
  )
}

function RowNode({ hallId, row, rackId, selected }: { hallId: number; row: HallLayoutRow; rackId?: number; selected: boolean }) {
  const [open, setOpen] = useState(selected || row.racks.some((r) => r.id === rackId))
  return (
    <li role="treeitem" aria-expanded={open} aria-selected={selected}>
      <div className="tree-row">
        <Toggle open={open} onClick={() => setOpen(!open)} label={row.name} />
        <Link to={`/halls/${hallId}/rows/${row.id}`} className={selected ? 'tree-link active' : 'tree-link'} aria-current={selected ? 'page' : undefined}>{row.name}</Link>
      </div>
      {open && (
        <ul role="group">
          {sortCabinets(row.racks).map((r) => (
            <CabinetNode key={r.id} hallId={hallId} rack={r} selected={r.id === rackId} />
          ))}
        </ul>
      )}
    </li>
  )
}

function HallNode({ id, name, current, rackId, rowId }: { id: number; name: string; current: boolean; rackId?: number; rowId?: number }) {
  const [open, setOpen] = useState(current)
  const { data } = useHallLayout(id, open)
  return (
    <li role="treeitem" aria-expanded={open} aria-selected={current && !rackId && !rowId}>
      <div className="tree-row">
        <Toggle open={open} onClick={() => setOpen(!open)} label={name} />
        <Link to={`/halls/${id}`} className={current && !rackId && !rowId ? 'tree-link active' : 'tree-link'}>{name}</Link>
      </div>
      {open && data && (
        <ul role="group">
          {sortRows(data.rows).map((r) => (
            <RowNode key={r.id} hallId={id} row={r} rackId={rackId} selected={r.id === rowId} />
          ))}
        </ul>
      )}
    </li>
  )
}

export default function Tree() {
  const params = useParams()
  const hallId = params.hallId ? Number(params.hallId) : undefined
  const rackId = params.rackId ? Number(params.rackId) : undefined
  const rowId = params.rowId ? Number(params.rowId) : undefined
  const { data, error } = useHalls()
  if (error) return <p className="error">{error.message}</p>
  return (
    <ul className="tree" role="tree" aria-label="Data halls">
      {(data?.items ?? []).map((h) => (
        <HallNode key={`${h.id}-${hallId === h.id}`} id={h.id} name={h.name} current={hallId === h.id} rackId={rackId} rowId={rowId} />
      ))}
    </ul>
  )
}
