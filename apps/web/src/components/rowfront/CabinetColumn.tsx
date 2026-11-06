// One cabinet column: frame, RU slot gradient, device blocks, empty runs, drop target.
import { memo, type DragEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { deviceAria, deviceU, type Column, type ColItem, type Lod, type RowFrontDevice } from '../../lib/rowFront'
import DeviceFront from './DeviceFront'

export const FRAME = 4

export interface Ghost { top: number; bottom: number; ok: boolean; reason?: string }

interface Props {
  col: Column
  colIndex: number
  rowU: number
  ru: number
  width: number
  lod: Lod
  face: 'front' | 'rear'
  selectedId: number | null
  focusKey: string | null
  canMove: boolean
  ghost: Ghost | null
  dragging: boolean
  onItemClick: (col: number, item: ColItem, u: number) => void
  onItemDouble: (col: number, item: ColItem) => void
  onItemFocus: (col: number, top: number) => void
  onKeyDown: (e: KeyboardEvent) => void
  onDragStartDevice: (col: number, d: RowFrontDevice, e: DragEvent) => void
  onDragEnd: () => void
  onDragOverU: (col: number, topU: number) => void
  onDropCol: (col: number) => void
}

function CabinetColumn(p: Props) {
  const { col, colIndex, rowU, ru, width, lod } = p
  const offset = (rowU - col.u) * ru // 42U next to 53U: bottom-aligned, top hatched
  const y = (top: number) => FRAME + (rowU - top) * ru
  const uFromEvent = (e: { clientY: number; currentTarget: Element }) => {
    const rect = e.currentTarget.getBoundingClientRect()
    return Math.min(rowU, Math.max(1, rowU - Math.floor((e.clientY - rect.top - FRAME) / ru)))
  }
  const over = (e: DragEvent) => {
    if (!p.dragging) return
    e.preventDefault()
    p.onDragOverU(colIndex, uFromEvent(e))
  }
  return (
    <div
      className={`rf-col${p.dragging ? ' dragging' : ''}`}
      style={{ width, height: rowU * ru + FRAME * 2, ['--ru' as string]: `${ru}px` }}
      role="row"
      aria-label={`Cabinet ${col.rack.name}, ${col.u}U`}
      data-testid={`cabinet-${col.rack.id}`}
      onDragOver={over}
      onDrop={(e) => { if (p.dragging) { e.preventDefault(); p.onDropCol(colIndex) } }}
    >
      {offset > 0 && <div className="rf-norails" style={{ top: FRAME, height: offset }} title={`No rails: ${col.u}U cabinet`} aria-hidden="true" />}
      <div className="rf-slots" style={{ top: FRAME + offset, height: col.u * ru }} aria-hidden="true" />
      {col.behind.map((d) => (
        <div key={`b${d.id}`} className="rf-behind" style={{ top: y(d.position_u + deviceU(d) - 1), height: deviceU(d) * ru }} aria-hidden="true">
          {lod >= 2 && <span>{p.face === 'front' ? 'rear' : 'front'}: {d.host_name}</span>}
        </div>
      ))}
      {col.items.map((it) => {
        const key = `${colIndex}:${it.top}`
        const style = { top: y(it.top), height: (it.top - it.bottom + 1) * ru }
        const common = {
          role: 'gridcell',
          tabIndex: p.focusKey === key ? 0 : -1,
          'data-cell': key,
          onFocus: () => p.onItemFocus(colIndex, it.top),
          onKeyDown: p.onKeyDown,
          onDoubleClick: () => p.onItemDouble(colIndex, it),
        }
        if (it.kind === 'device') {
          const d = it.device
          const movable = p.canMove && lod >= 1 && !it.passThrough
          return (
            <div
              key={`d${d.id}`} {...common}
              className={`rf-dev${p.selectedId === d.id ? ' selected' : ''}`}
              style={style}
              aria-label={deviceAria(d, col.rack.name, it.passThrough)}
              aria-selected={p.selectedId === d.id}
              title={`${d.host_name}${d.device_type ? ` · ${d.device_type.manufacturer} ${d.device_type.name}` : ''}`}
              draggable={movable}
              onDragStart={movable ? (e) => p.onDragStartDevice(colIndex, d, e) : undefined}
              onDragEnd={movable ? p.onDragEnd : undefined}
              onClick={(e: MouseEvent) => p.onItemClick(colIndex, it, uFromEvent({ clientY: e.clientY, currentTarget: e.currentTarget.parentElement! }))}
            >
              <DeviceFront device={d} lod={lod} ru={ru} passThrough={it.passThrough} conflict={it.conflict} />
            </div>
          )
        }
        const n = it.top - it.bottom + 1
        return (
          <div
            key={`e${it.top}`} {...common}
            className="rf-empty"
            style={style}
            aria-label={`Empty, cabinet ${col.rack.name}, RU ${it.bottom}${n > 1 ? ` to ${it.top}` : ''}, ${n} free`}
            onClick={(e: MouseEvent) => p.onItemClick(colIndex, it, uFromEvent({ clientY: e.clientY, currentTarget: e.currentTarget.parentElement! }))}
          >
            {lod < 2 && n >= 3 && n * ru >= 24 && <span className="rf-free">{n} free</span>}
            {lod >= 2 && <span className="rf-plus" aria-hidden="true">+</span>}
          </div>
        )
      })}
      {p.ghost && (
        <div className={`rf-ghost ${p.ghost.ok ? 'ok' : 'bad'}`} style={{ top: y(p.ghost.top), height: (p.ghost.top - p.ghost.bottom + 1) * ru }} data-testid="drop-ghost">
          <span>{p.ghost.ok ? '✓ Drop here' : `✕ ${p.ghost.reason}`}</span>
        </div>
      )}
    </div>
  )
}

export default memo(CabinetColumn)
