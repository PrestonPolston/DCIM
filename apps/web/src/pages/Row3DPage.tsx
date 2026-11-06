// 3D row view: /halls/:hallId/rows/:rowId[?face=rear&cabinet=:rackId&device=:id]
// (docs/design/row-3d.md; ROW_3D_SPIKE.md). Data: useRowFront (GET /rows/{id}/front adapter).
// The three.js canvas is a React.lazy chunk; this page shell is tiny.
import { lazy, Suspense, useCallback, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { devicesApi } from '../api/client'
import { useUpdateDevice } from '../api/devices'
import { useCan } from '../auth/auth'
import DeviceForm from '../components/DeviceForm'
import { useProfiles } from '../api/profiles'
import { useRowFront } from '../api/rowFront'
import DeviceCard from '../components/row3d/DeviceCard'
import { ruRange, selectionText } from '../lib/deviceText'
import { placeHoverCard, type Rect } from '../lib/hoverCard'
import Row3DBoundary from '../components/row3d/Row3DBoundary'
import type { Label, Row3DHandle } from '../components/row3d/Row3DView'
import { buildRowScene, navigate, type Face3D } from '../lib/row3d'
import { cabinetOrder, type RowFrontDevice, type RowFrontRack } from '../lib/rowFront'
import { statusIcon, statusLabel } from '../lib/status'
import { NO_3D_TEXT, prefersReducedMotion } from '../lib/webgl'
import RowFrontPage from './RowFrontPage'

const Row3DView = lazy(() => import('../components/row3d/Row3DView'))

export default function Row3DPage() {
  const hallId = Number(useParams().hallId)
  const rowId = Number(useParams().rowId)
  const [params, setParams] = useSearchParams()
  const { data, isPending, error, notFound } = useRowFront(hallId, rowId)
  const profiles = useProfiles({ status: 'all' }).all
  const view = useRef<Row3DHandle | null>(null)
  const [fatal, setFatalState] = useState<Error | null>(null)
  const setFatal = useCallback((e: Error) => { console.error('[3D row] falling back to 2D:', e); setFatalState(e) }, [])
  const [side, setSide] = useState<Face3D>(params.get('face') === 'rear' ? 'rear' : 'front')
  const [hover, setHover] = useState<{ id: number; left: number; top: number } | null>(null)
  const [highlight, setHighlight] = useState<'none' | 'status'>('none')
  const [labels, setLabels] = useState(true)
  const [list, setList] = useState(false)
  const stageRef = useRef<HTMLDivElement | null>(null)

  const setParam = useCallback((patch: Record<string, string | null>) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) if (v == null) next.delete(k); else next.set(k, v)
      return next
    }, { replace: true })
  }, [setParams])

  // Cabinets left→right as seen from the FRONT; the camera moves for the rear (no row flip).
  const racks = useMemo(() => (data ? cabinetOrder(data.racks, data.row.effective_facing, 'front').racks : []), [data])
  const scene = useMemo(() => buildRowScene(racks), [racks])
  const selectedId = params.get('device') ? Number(params.get('device')) : null
  const cabinetParam = params.get('cabinet') ? Number(params.get('cabinet')) : null
  const where = useMemo(() => {
    const m = new Map<number, { dev: RowFrontDevice; rack: RowFrontRack; index: number }>()
    racks.forEach((rack, index) => rack.devices.forEach((dev) => m.set(dev.id, { dev, rack, index })))
    return m
  }, [racks])
  const sel = selectedId != null ? where.get(selectedId) : undefined
  const focusIdx = cabinetParam != null ? racks.findIndex((r) => r.id === cabinetParam) : sel?.index ?? -1
  const variantName = (id?: number | null) => {
    const p = id != null ? profiles.find((x) => x.id === id) : undefined
    return p && !p.isDefault ? p.name : null
  }
  const canEdit = useCan('device.write')
  const update = useUpdateDevice()
  const [editing, setEditing] = useState<number | null>(null)
  const editQuery = useQuery({ queryKey: ['devices', 'one', editing], queryFn: () => devicesApi.get(editing!), enabled: editing != null })

  // Read once by Row3DView on its first scene.
  const initial = { side, cabinet: focusIdx >= 0 ? focusIdx : null }

  // aria-live selection line (the canvas is aria-hidden; List is the accessible path).
  const selText = sel ? selectionText(sel.dev, sel.rack.name) : null
  const [prevSel, setPrevSel] = useState<string | null>(selText)
  const [live, setLive] = useState(selText ?? '')
  if (prevSel !== selText) { setPrevSel(selText); setLive(selText ?? (prevSel ? 'Selection cleared' : '')) }

  // Device names are never always-on: the selected device gets a name tag, hover gets the card.
  const tag: Label | null = useMemo(() => (sel ? { id: sel.dev.id, text: sel.dev.host_name } : null), [sel])

  if (fatal) {
    return <RowFrontPage notice={NO_3D_TEXT} noticeDetail={fatal.message} />
  }
  if (isPending) return <p className="hint">Loading row…</p>
  if (error) return <p className="error" role="alert">Couldn't load this row: {error.message}</p>
  if (notFound || !data) return <p className="hint">Row not found in this hall.</p>

  // One setParams per action: react-router's functional updater doesn't compose within a tick.
  const focus = (i: number, extra: Record<string, string | null> = {}) => {
    if (i < 0 || i >= racks.length) return
    setParam({ cabinet: String(racks[i].id), ...extra })
    view.current?.focusCabinet(i)
  }
  const select = (id: number | null) => {
    setParam({ device: id == null ? null : String(id) })
    setHover(null)
  }
  const selectAndFocus = (id: number) => {
    setHover(null)
    const w = where.get(id)
    if (w && w.index !== focusIdx) focus(w.index, { device: String(id) })
    else setParam({ device: String(id) })
  }
  const flip = () => view.current?.flip()
  const step = (dir: 1 | -1) => {
    // From the rear, screen-right is the previous cabinet in front order.
    const d = side === 'rear' ? -dir : dir
    focus(focusIdx < 0 ? (d > 0 ? 0 : racks.length - 1) : Math.max(0, Math.min(racks.length - 1, focusIdx + d)))
  }
  const reset = () => { setParam({ cabinet: null }); view.current?.preset('reset') }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    if (e.key.startsWith('Arrow')) {
      e.preventDefault()
      const id = navigate(racks, selectedId, e.key, side)
      if (id != null) selectAndFocus(id)
    } else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); flip() }
    else if (e.key === 'Escape') select(null)
    else if (e.key === '0') { setParam({ cabinet: null }); view.current?.preset('fit') }
    else if (e.key === '+' || e.key === '=' || e.key === '-') view.current?.zoom(e.key === '-' ? 1.25 : 0.8)
    else if (e.key === 'Enter' && sel) document.querySelector<HTMLElement>('.r3d-detail a, .r3d-detail button')?.focus()
  }

  const hov = hover ? where.get(hover.id) : undefined
  const path = `${data.hall.name} › ${data.row.name}`
  const openHref = (rack: RowFrontRack, d?: RowFrontDevice) => `/halls/${hallId}/cabinets/${rack.id}${d ? `?device=${d.id}` : ''}`
  const counts = new Map<string, number>()
  for (const r of racks) for (const d of r.devices) counts.set(d.status, (counts.get(d.status) ?? 0) + 1)

  return (
    <section className="row3d-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={`/halls/${hallId}`}>{data.hall.name}</Link> › <span aria-current="page">{data.row.name}</span>
        {' '}<span className="chip r3d-side-chip">{side === 'front' ? 'Front (aisle)' : 'Rear'}</span>
      </nav>
      <div className="rf-toolbar r3d-toolbar" role="toolbar" aria-label="3D row view">
        <div className="segmented" role="group" aria-label="Side">
          <button type="button" aria-pressed={side === 'front'} onClick={() => view.current?.setSide('front')}>Front</button>
          <button type="button" aria-pressed={side === 'rear'} onClick={() => view.current?.setSide('rear')}>Rear</button>
        </div>
        <div className="r3d-tb-group" role="group" aria-label="Cabinet">
          <button type="button" className="icon" aria-label="Previous cabinet" onClick={() => step(-1)}>‹</button>
          <span className="r3d-focus" aria-live="polite">{focusIdx >= 0 ? racks[focusIdx]?.name : 'Whole row'}</span>
          <button type="button" className="icon" aria-label="Next cabinet" onClick={() => step(1)}>›</button>
        </div>
        <div className="r3d-tb-group" role="group" aria-label="Camera">
          <button type="button" onClick={() => { setParam({ cabinet: null }); view.current?.preset('fit') }}>Fit row</button>
          <button type="button" onClick={reset}>Reset</button>
        </div>
        <label className="r3d-select">Highlight{' '}
          <select value={highlight} onChange={(e) => setHighlight(e.target.value as 'none' | 'status')}>
            <option value="none">None</option>
            <option value="status">Status</option>
          </select>
        </label>
        <button type="button" aria-pressed={labels} onClick={() => setLabels(!labels)} title="Row and cabinet names. Device names appear on hover and selection.">Labels</button>
        {/* X-ray: not in v1 (Designer, Oct 2026). A visible, inert slot; aria-disabled keeps it in tab order without trapping focus. */}
        <button type="button" className="r3d-later" aria-disabled="true" title="X-ray: later" onClick={(e) => e.preventDefault()}>X-ray <span className="hint">later</span></button>
        <div className="r3d-tb-group r3d-tb-end" role="group" aria-label="View">
          <button type="button" aria-pressed={list} onClick={() => setList(!list)}>List</button>
          <Link className="button" to={`?${new URLSearchParams({ view: '2d', ...(side === 'rear' ? { face: 'rear' } : {}), ...(selectedId ? { device: String(selectedId) } : {}) })}`}>2D</Link>
        </div>
      </div>
      <p className="hint r3d-status">
        Highlighting: {highlight === 'none' ? 'None' : 'Status'}
        {highlight === 'status' && [...counts].map(([s, n]) => <span key={s} className={`r3d-legend r3d-legend-${s}`}> <span aria-hidden="true">{statusIcon(s)}</span> {statusLabel(s)} {n}</span>)}
      </p>
      <p className="sr-only r3d-live" role="status" aria-live="polite" data-testid="r3d-live">{live}</p>
      <div className={`r3d-body${sel ? ' with-panel' : ''}`}>
        <div className="r3d-box" ref={stageRef} tabIndex={0} onKeyDown={onKey}
          role="application" aria-roledescription="3D row view"
          aria-label={`${data.row.name}: ${racks.length} cabinets in 3D, ${side} side. Arrow keys select devices, F flips, 0 resets, Esc clears. Use List for a text version.`}>
          {racks.length === 0 ? <p className="hint">No cabinets in this row yet.</p> : (
            <Row3DBoundary fallback={(e) => { queueMicrotask(() => setFatal(e)); return null }}>
              <Suspense fallback={<p className="hint r3d-loading">Loading 3D view…</p>}>
                <Row3DView
                  ref={view} scene={scene} selectedId={selectedId} highlight={highlight}
                  initial={initial} reducedMotion={prefersReducedMotion()}
                  tag={tag} rowName={data.row.name} cabinetLabels={labels} marker={sel ? selectedId : null}
                  onPick={select}
                  onHover={(id, x, y, rect) => {
                    const b = stageRef.current?.getBoundingClientRect()
                    setHover(id == null || !b ? null : { id, ...hoverPos(x - b.left, y - b.top, b.width, b.height, rect ? { left: rect.left - b.left, top: rect.top - b.top, right: rect.right - b.left, bottom: rect.bottom - b.top } : null) })
                  }}
                  onFocusCabinet={focus}
                  onView={(s) => { setSide(s); setParam({ face: s === 'rear' ? 'rear' : null }) }}
                  onFatal={setFatal}
                />
              </Suspense>
            </Row3DBoundary>
          )}
          {hov && hover && hov.dev.id !== selectedId && (
            <div className="r3d-hover-wrap" style={{ left: hover.left, top: hover.top }}>
              <DeviceCard device={hov.dev} rack={hov.rack} variantName={variantName(hov.dev.profile_id)} path={path} variant="hover" />
            </div>
          )}
        </div>
        {sel && (
          <aside className="r3d-detail-wrap">
            <DeviceCard device={sel.dev} rack={sel.rack} variantName={variantName(sel.dev.profile_id)} path={path} variant="detail"
              openHref={openHref(sel.rack, sel.dev)} onEdit={canEdit ? () => setEditing(sel.dev.id) : undefined} onClose={() => select(null)} />
          </aside>
        )}
      </div>
      {list && <RowList racks={racks} selectedId={selectedId} onSelect={selectAndFocus} />}
      {editing != null && editQuery.data && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Edit device">
          <DeviceForm
            device={editQuery.data} title={`Edit ${editQuery.data.host_name}`}
            onSubmit={async (v) => { await update.mutateAsync({ id: editing, body: v }); setEditing(null) }}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}
    </section>
  )
}

/** Card beside the hovered cabinet, on the side with more free canvas (never covering it). */
function hoverPos(x: number, y: number, w: number, h: number, avoid: Rect | null): { left: number; top: number } {
  const p = placeHoverCard(avoid, x, y, w, h, 280, 280) // card is ~270 px tall with the full field set
  return { left: p.left, top: p.top }
}

/** Accessible text version of the same data: Cabinet → RU → host name, profile, status, face. */
function RowList({ racks, selectedId, onSelect }: { racks: RowFrontRack[]; selectedId: number | null; onSelect: (id: number) => void }) {
  return (
    <div className="card r3d-list">
      <h2>Devices in this row</h2>
      {racks.map((r) => (
        <section key={r.id}>
          <h3>{r.name}</h3>
          {r.devices.length === 0 ? <p className="hint">Empty</p> : (
            <ol>
              {[...r.devices].sort((a, b) => b.position_u - a.position_u).map((d) => (
                <li key={d.id}>
                  <button type="button" className="link" aria-pressed={d.id === selectedId} onClick={() => onSelect(d.id)}>{ruRange(d)} · {d.host_name}</button>
                  {' '}· {d.device_type ? `${d.device_type.manufacturer} ${d.device_type.name}` : 'No profile'} · {statusLabel(d.status)}{d.face === 'rear' ? ' · rear' : ''}
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  )
}
