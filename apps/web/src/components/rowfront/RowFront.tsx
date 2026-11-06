// Scroll container for the row front view: cabinets side by side, sticky ruler
// and headers, LOD by px/RU, keyboard grid, drag within/across cabinets
// (row-front.md §1–§6). Data and mutations live in RowFrontPage.
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import type { Face } from '../../api/types'
import type { PlacingProfile } from '../../api/profiles'
import { canPlace, checkFit, keyMoveStep, positionFromTop, type KeyMove, type Spot } from '../../lib/placement'
import {
  buildColumn, deviceU, lod as lodOf, navigate, rowHeightU, toElevationDevice,
  type ColItem, type Column, type Cursor, type RowFrontDevice, type RowFrontRack,
} from '../../lib/rowFront'
import CabinetColumn, { FRAME, type Ghost } from './CabinetColumn'
import CabinetHeader from './CabinetHeader'
import { FallbackSymbols } from './FallbackFront'
import Ruler from './Ruler'

export interface MoveRequest { device: RowFrontDevice; from: Spot; to: Spot }

interface Props {
  racks: RowFrontRack[] // already in on-screen order
  face: Face
  ru: number
  cw: number
  gap: number
  ruler: number
  /** Render only columns in view ± 1 (Detail). */
  virtualize: boolean
  selectedId: number | null
  canMove: boolean
  onSelect: (d: RowFrontDevice | null, rack?: RowFrontRack) => void
  onOpenDevice: (d: RowFrontDevice, rack: RowFrontRack) => void
  onOpenCabinet: (rack: RowFrontRack) => void
  onEmpty: (rack: RowFrontRack, position_u: number) => void
  /** L0: a tap on a cabinet zooms to Detail centred on it. */
  onZoomTo: (colIndex: number) => void
  onMove: (req: MoveRequest) => void
  onZoomKey: (key: '+' | '-' | '0') => void
  scrollRef?: React.RefObject<HTMLDivElement | null>
  /** A profile picked or dragged from the palette: empty RUs become drop targets. */
  placing?: PlacingProfile | null
  onPlaceProfile?: (rack: RowFrontRack, position_u: number) => void
}

const spot = (rack: RowFrontRack, position_u: number, face: Face): Spot => ({ rackId: rack.id, rackName: rack.name, position_u, face })

export default function RowFront(p: Props) {
  const { racks, face, ru, cw, gap, ruler } = p
  const lod = lodOf(ru)
  const cols = useMemo<Column[]>(() => racks.map((r) => buildColumn(r, face)), [racks, face])
  const rowU = rowHeightU(racks)
  const innerRef = useRef<HTMLDivElement | null>(null)
  const ownRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = p.scrollRef ?? ownRef
  const [cursor, setCursor] = useState<Cursor | null>(null)
  const [drag, setDrag] = useState<{ col: number; device: RowFrontDevice } | null>(null)
  const [over, setOver] = useState<{ col: number; position_u: number } | null>(null)
  const [keyMove, setKeyMove] = useState<(KeyMove & { device: RowFrontDevice; fromCol: number }) | null>(null)
  const [view, setView] = useState({ left: 0, width: 0 })
  const focusPending = useRef(false)

  const fitOf = useCallback((ci: number, d: RowFrontDevice, position_u: number, f: Face) => {
    const col = cols[ci]
    return checkFit(col.u, col.rack.devices.map(toElevationDevice), toElevationDevice(d), position_u, f)
  }, [cols])

  // Focus follows the keyboard cursor.
  useEffect(() => {
    if (!cursor || !focusPending.current) return
    focusPending.current = false
    const el = innerRef.current?.querySelector<HTMLElement>(`[data-cell="${cursor.col}:${cursor.u}"]`)
    el?.focus()
    el?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [cursor])

  const itemOf = (c: Cursor) => cols[c.col]?.items.find((i) => i.top === c.u)

  const onKeyDown = (e: KeyboardEvent) => {
    if (keyMove) {
      e.preventDefault()
      if (e.key === 'Escape') return setKeyMove(null)
      if (e.key === 'Enter') {
        const fit = fitOf(keyMove.col, keyMove.device, keyMove.position_u, keyMove.face)
        if (fit.ok) {
          p.onMove({ device: keyMove.device, from: spot(cols[keyMove.fromCol].rack, keyMove.device.position_u, keyMove.device.face), to: spot(cols[keyMove.col].rack, keyMove.position_u, keyMove.face) })
          setKeyMove(null)
        }
        return
      }
      const next = keyMoveStep(keyMove, e.key, cols, deviceU(keyMove.device))
      if (next) setKeyMove({ ...keyMove, ...next })
      return
    }
    if (!cursor) return
    const it = itemOf(cursor)
    const rack = cols[cursor.col].rack
    if (e.key === 'Enter' && it) {
      e.preventDefault()
      if (it.kind === 'device') p.onOpenDevice(it.device, rack)
      else if (p.canMove) p.onEmpty(rack, it.bottom)
      return
    }
    if (e.key === ' ' && it) {
      e.preventDefault()
      p.onSelect(it.kind === 'device' ? it.device : null, rack)
      return
    }
    if (e.key === 'Escape') return p.onSelect(null)
    if ((e.key === 'm' || e.key === 'M') && p.canMove && it?.kind === 'device' && !it.passThrough) {
      e.preventDefault()
      setKeyMove({ device: it.device, fromCol: cursor.col, col: cursor.col, position_u: it.device.position_u, face: it.device.face })
      return
    }
    if (e.key === '+' || e.key === '=' || e.key === '-' || e.key === '0') {
      e.preventDefault()
      return p.onZoomKey(e.key === '=' ? '+' : (e.key as '+' | '-' | '0'))
    }
    const next = navigate(cols, cursor, e.key)
    if (next) {
      e.preventDefault()
      focusPending.current = true
      setCursor(next)
    }
  }

  const onItemClick = (ci: number, it: ColItem, u: number) => {
    setCursor({ col: ci, u: it.top })
    if (lod === 0) return p.onZoomTo(ci)
    const at = Math.min(Math.max(u, it.bottom), it.top)
    if (it.kind === 'device') p.onSelect(it.device, cols[ci].rack)
    else if (p.canMove && p.placing) {
      const pos = Math.max(it.bottom, Math.min(at, it.top - p.placing.uHeight + 1))
      if (placeFit(ci, pos).ok) p.onPlaceProfile?.(cols[ci].rack, pos)
    } else if (p.canMove) p.onEmpty(cols[ci].rack, at)
  }
  const onItemDouble = (ci: number, it: ColItem) => {
    if (it.kind === 'device') p.onOpenDevice(it.device, cols[ci].rack)
  }

  const onDragStartDevice = (ci: number, d: RowFrontDevice, e: DragEvent) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(d.id))
    setDrag({ col: ci, device: d })
  }
  const endDrag = () => { setDrag(null); setOver(null) }
  const placeFit = (ci: number, position_u: number) =>
    canPlace(cols[ci].u, cols[ci].rack.devices.map(toElevationDevice), { height_u: p.placing!.uHeight, is_full_depth: p.placing!.isFullDepth }, position_u, face)
  const onDragOverU = (ci: number, topU: number) => {
    if (p.placing && !drag) {
      const pos = Math.max(1, positionFromTop(topU, p.placing.uHeight))
      if (!over || over.col !== ci || over.position_u !== pos) setOver({ col: ci, position_u: pos })
      return
    }
    if (!drag) return
    const pos = Math.max(1, positionFromTop(topU, deviceU(drag.device)))
    if (!over || over.col !== ci || over.position_u !== pos) setOver({ col: ci, position_u: pos })
    // Auto-scroll near the container edges is left to the browser's native DnD auto-scroll.
  }
  const onDropCol = (ci: number) => {
    if (p.placing && !drag) {
      const o = over
      setOver(null)
      if (o && o.col === ci && placeFit(ci, o.position_u).ok) p.onPlaceProfile?.(cols[ci].rack, o.position_u)
      return
    }
    if (!drag || !over || over.col !== ci) return endDrag()
    const d = drag.device
    const fit = fitOf(ci, d, over.position_u, face)
    const from = spot(cols[drag.col].rack, d.position_u, d.face)
    const to = spot(cols[ci].rack, over.position_u, face)
    endDrag()
    if (fit.ok && !(from.rackId === to.rackId && from.position_u === to.position_u && from.face === to.face)) p.onMove({ device: d, from, to })
  }

  const ghostFor = (ci: number): Ghost | null => {
    const g = keyMove ? { col: keyMove.col, position_u: keyMove.position_u, device: keyMove.device, f: keyMove.face }
      : drag && over ? { col: over.col, position_u: over.position_u, device: drag.device, f: face } : null
    if (!g && p.placing && over && over.col === ci) {
      const fit = placeFit(ci, over.position_u)
      return { top: Math.min(cols[ci].u, over.position_u + p.placing.uHeight - 1), bottom: over.position_u, ok: fit.ok, reason: fit.ok ? undefined : fit.reason }
    }
    if (!g || g.col !== ci) return null
    const h = deviceU(g.device)
    const fit = fitOf(ci, g.device, g.position_u, g.f)
    const top = Math.min(cols[ci].u, g.position_u + h - 1)
    return { top, bottom: g.position_u, ok: fit.ok, reason: fit.ok ? undefined : `${fit.reason}${g.f !== face ? ` (${g.f})` : ''}` }
  }

  // Horizontal virtualization (Detail only).
  const onScroll = () => {
    const el = scrollRef.current
    if (el && p.virtualize) setView({ left: el.scrollLeft, width: el.clientWidth })
  }
  useEffect(() => { onScroll() }, [p.virtualize, cw]) // eslint-disable-line react-hooks/exhaustive-deps
  const step = cw + gap
  const [first, last] = p.virtualize && view.width > 0
    ? [Math.max(0, Math.floor((view.left - ruler) / step) - 1), Math.min(cols.length - 1, Math.ceil((view.left + view.width - ruler) / step) + 1)]
    : [0, cols.length - 1]

  const focusKey = cursor ? `${cursor.col}:${cursor.u}` : cols[0]?.items[0] ? `0:${cols[0].items[0].top}` : null
  const height = rowU * ru + FRAME * 2
  return (
    <div className="rf-scroll" ref={scrollRef} onScroll={onScroll}>
      <FallbackSymbols />
      <div
        ref={innerRef}
        className={`rf-grid rf-l${lod}`}
        role="grid"
        aria-label={`Row cabinets, ${face} view`}
        aria-colcount={cols.length}
        style={{ ['--gap' as string]: `${gap}px` }}
      >
        <div className="rf-corner" style={{ width: ruler }}>RU</div>
        <div className="rf-heads" style={{ gap }}>
          {cols.map((c, i) => (i < first || i > last
            ? <div key={c.rack.id} style={{ width: cw }} />
            : <CabinetHeader key={c.rack.id} rack={c.rack} width={cw} compact={cw < 48} onOpen={() => p.onOpenCabinet(c.rack)} />))}
        </div>
        <Ruler rowU={rowU} ru={ru} width={ruler} frame={0} />
        <div className="rf-cols" style={{ gap, height }}>
          {cols.map((c, i) => (i < first || i > last
            ? <div key={c.rack.id} style={{ width: cw }} />
            : (
              <CabinetColumn
                key={c.rack.id} col={c} colIndex={i} rowU={rowU} ru={ru} width={cw} lod={lod} face={face}
                selectedId={p.selectedId} focusKey={focusKey} canMove={p.canMove}
                ghost={ghostFor(i)} dragging={!!drag || !!p.placing}
                onItemClick={onItemClick} onItemDouble={onItemDouble}
                onItemFocus={(col, top) => setCursor((cur) => (cur && cur.col === col && cur.u === top ? cur : { col, u: top }))}
                onKeyDown={onKeyDown}
                onDragStartDevice={onDragStartDevice} onDragEnd={endDrag} onDragOverU={onDragOverU} onDropCol={onDropCol}
              />
            )))}
        </div>
      </div>
      {keyMove && (
        <p className="rf-keymove" role="status">
          Moving {keyMove.device.host_name}: ←/→ cabinet, ↑/↓ RU, F face, Enter to confirm, Esc to cancel.
        </p>
      )}
    </div>
  )
}
