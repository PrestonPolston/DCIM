// Row front view route: /halls/:hallId/rows/:rowId?face=front&zoom=fit&device=:id
// (docs/design/row-front.md). Data comes only from api/rowFront.ts.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ApiError, devicesApi } from '../api/client'
import { useCreateDevice, useUpdateDevice } from '../api/devices'
import { useRowFront } from '../api/rowFront'
import type { DeviceCreate, Face } from '../api/types'
import { useCan } from '../auth/auth'
import DeviceForm from '../components/DeviceForm'
import ProfilePalette from '../components/profiles/ProfilePalette'
import ChooseProfileSheet from '../components/profiles/ChooseProfileSheet'
import AddProfileDialog from '../components/profiles/AddProfileDialog'
import { placementBody, useProfiles, type PlacingProfile } from '../api/profiles'
import { FaceToggle, ZoomControls } from '../components/rowfront/Controls'
import DeviceSidePanel from '../components/rowfront/DeviceSidePanel'
import MovePicker from '../components/rowfront/MovePicker'
import RowFront, { type MoveRequest } from '../components/rowfront/RowFront'
import { describeMove, moveBody, type Spot } from '../lib/placement'
import {
  cabinetOrder, detailCw, fitCw, fitRu, PHONE_DETAIL_RU, RU_FIT_MIN, rowHeightU, rowSummary,
  viewportMetrics, zoomStep, type RowFrontDevice, type RowFrontRack,
} from '../lib/rowFront'
import { statusIcon, statusLabel } from '../lib/status'
import { hasWebGL } from '../lib/webgl'

const HDR = 40
const UNDO_MS = 10_000

function useSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight })
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

export default function RowFrontPage({ notice, noticeDetail }: { notice?: string; noticeDetail?: string } = {}) {
  const hallId = Number(useParams().hallId)
  const rowId = Number(useParams().rowId)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const face: Face = params.get('face') === 'rear' ? 'rear' : 'front'
  const zoomParam = params.get('zoom') ?? 'fit'
  const selectedId = params.get('device') ? Number(params.get('device')) : null
  const canMove = useCan('device.write')
  const { data, isPending, error, notFound } = useRowFront(hallId, rowId)
  const [boxRef, box] = useSize<HTMLDivElement>()
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const setParam = useCallback((patch: Record<string, string | null>) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) if (v == null) next.delete(k); else next.set(k, v)
      return next
    }, { replace: true })
  }, [setParams])

  const order = useMemo(() => (data ? cabinetOrder(data.racks, data.row.effective_facing, face) : null), [data, face])
  const racks = order?.racks ?? []
  const m = viewportMetrics(box.w || 1440)
  const rowU = rowHeightU(racks)
  const fit = zoomParam === 'fit'
  const ru = fit ? (m.phone ? RU_FIT_MIN : fitRu(box.h - HDR, rowU)) : Number(zoomParam) || 24
  const cw = fit ? fitCw(box.w || 1160, racks.length, m.ruler, m.gap) : detailCw(ru)

  // Confirm / undo / dialogs
  const update = useUpdateDevice()
  const create = useCreateDevice()
  const [confirm, setConfirm] = useState<MoveRequest | null>(null)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ text: string; undo?: { id: number; to: Spot } } | null>(null)
  const [place, setPlace] = useState<{ rack: RowFrontRack; position_u: number; profile: PlacingProfile } | null>(null)
  const [choosing, setChoosing] = useState<{ rack: RowFrontRack; position_u: number } | null>(null)
  const [placing, setPlacing] = useState<PlacingProfile | null>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const allProfiles = useProfiles({ status: 'all' }).all
  const [editing, setEditing] = useState<number | null>(null)
  const [picking, setPicking] = useState<RowFrontDevice | null>(null)
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), UNDO_MS)
    return () => clearTimeout(t)
  }, [toast])

  const doMove = async () => {
    if (!confirm) return
    setConfirmError(null)
    try {
      await update.mutateAsync({ id: confirm.device.id, body: moveBody(confirm.to) })
      setToast({ text: `${describeMove(confirm.device.host_name, confirm.from, confirm.to).replace(/^Move/, 'Moved')}`, undo: { id: confirm.device.id, to: confirm.from } })
      setConfirm(null)
    } catch (e) {
      setConfirmError(e instanceof ApiError || e instanceof Error ? e.message : 'Move failed')
    }
  }
  const undo = async () => {
    const u = toast?.undo
    if (!u) return
    setToast(null)
    try {
      await update.mutateAsync({ id: u.id, body: moveBody(u.to) })
      setToast({ text: 'Move undone' })
    } catch (e) {
      setToast({ text: `Undo failed: ${e instanceof Error ? e.message : 'error'}` })
    }
  }

  const editQuery = useQuery({ queryKey: ['devices', 'one', editing], queryFn: () => devicesApi.get(editing!), enabled: editing != null })

  if (isPending) return <p className="hint">Loading row…</p>
  if (error) return <p className="error" role="alert">Couldn't load this row: {error.message}</p>
  if (notFound || !data || !order) return <p className="hint">Row not found in this hall.</p>

  const selRack = racks.find((r) => r.devices.some((d) => d.id === selectedId))
  const selDev = selRack?.devices.find((d) => d.id === selectedId)
  const sum = rowSummary(racks)
  const openCabinet = (rack: RowFrontRack, d?: RowFrontDevice) => navigate(`/halls/${hallId}/cabinets/${rack.id}${d ? `?device=${d.id}` : ''}`)
  const setZoom = (z: number | 'fit') => setParam({ zoom: String(z) })
  const step = (dir: 1 | -1) => setZoom(zoomStep(ru, dir))

  return (
    <section className="rowfront-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={`/halls/${hallId}`}>{data.hall.name}</Link> › <span aria-current="page">{data.row.name}</span>
      </nav>
      {notice && (
        <div className="banner r3d-notice">
          <p>{notice}</p>
          {noticeDetail && <details><summary>Details</summary><code>{noticeDetail}</code></details>}
        </div>
      )}
      <div className="rf-toolbar">
        {!notice && hasWebGL() && <button type="button" onClick={() => setParam({ view: null })}>3D</button>}
        <FaceToggle face={face} onChange={(f) => setParam({ face: f === 'front' ? null : f })} />
        <ZoomControls fit={fit} ru={ru} onFit={() => setZoom('fit')} onDetail={() => setZoom(m.phone ? PHONE_DETAIL_RU : 24)} onStep={step} />
        {order.left && order.right
          ? <span className="rf-compass" aria-label={`Left is ${order.left}, right is ${order.right}`}>← {order.left} · {order.right} →</span>
          : <span className="hint">{order.note}</span>}
        {canMove && <button type="button" aria-pressed={paletteOpen} onClick={() => setPaletteOpen(!paletteOpen)}>⇕ Profiles</button>}
      </div>
      {placing && (
        <p className="banner" role="status">
          Placing {placing.label}: choose a free RU, or press Esc. <button type="button" onClick={() => setPlacing(null)}>Cancel</button>
        </p>
      )}
      <div className={`rf-body${selDev ? ' with-panel' : ''}${paletteOpen && canMove ? ' with-palette' : ''}`} onKeyDown={(e) => { if (e.key === 'Escape') setPlacing(null) }}>
        {paletteOpen && canMove && (
          <ProfilePalette
            selectedId={placing?.profileId ?? null}
            onPick={setPlacing}
            onDragStart={setPlacing}
            onAddProfile={() => setAdding(true)}
          />
        )}
        <div className="rf-box" ref={boxRef}
          onWheel={(e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); step(e.deltaY < 0 ? 1 : -1) } }}>
          {racks.length === 0 ? <p className="hint">No cabinets in this row yet.</p> : (
            <RowFront
              racks={racks} face={face} ru={ru} cw={cw} gap={fit ? m.gap : 12} ruler={m.ruler}
              virtualize={!fit} selectedId={selectedId} canMove={canMove} scrollRef={scrollRef}
              onSelect={(d) => setParam({ device: d ? String(d.id) : null })}
              onOpenDevice={(d, rack) => openCabinet(rack, d)}
              onOpenCabinet={(rack) => openCabinet(rack)}
              onEmpty={(rack, position_u) => setChoosing({ rack, position_u })}
              placing={canMove ? placing : null}
              onPlaceProfile={(rack, position_u) => { if (placing) setPlace({ rack, position_u, profile: placing }); setPlacing(null) }}
              onZoomTo={(ci) => {
                const z = m.phone ? PHONE_DETAIL_RU : 24
                setZoom(z)
                requestAnimationFrame(() => scrollRef.current?.scrollTo?.({ left: ci * (detailCw(z) + 12) }))
              }}
              onMove={(req) => { setConfirmError(null); setConfirm(req) }}
              onZoomKey={(k) => (k === '0' ? setZoom('fit') : step(k === '+' ? 1 : -1))}
            />
          )}
        </div>
        {selDev && selRack && (
          <DeviceSidePanel
            device={selDev} rack={selRack} canMove={canMove}
            onClose={() => setParam({ device: null })}
            onOpenCabinet={() => openCabinet(selRack, selDev)}
            onEdit={() => setEditing(selDev.id)}
            onMove={() => setPicking(selDev)}
          />
        )}
      </div>
      <p className="rf-footer hint">
        {data.row.name} · {racks.length} cabinets · {sum.used}/{sum.total} RU used
        {[...sum.status].map(([s, n]) => <span key={s}> · <span aria-hidden="true">{statusIcon(s)}</span> {n} {statusLabel(s)}</span>)}
        {sum.noSerial > 0 && <span> · ⚑ {sum.noSerial} no serial</span>}
        {!canMove && <span> · Read-only: moving devices needs the Technician or Admin role.</span>}
      </p>

      {confirm && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Confirm move">
          <div className="card form">
            <h2>Move device?</h2>
            <p>{describeMove(confirm.device.host_name, confirm.from, confirm.to)}</p>
            {confirmError && <p className="field-error" role="alert">{confirmError}</p>}
            <div className="actions">
              <button type="button" onClick={() => setConfirm(null)} disabled={update.isPending}>Cancel</button>
              <button type="button" className="primary" onClick={doMove} disabled={update.isPending}>Move</button>
            </div>
          </div>
        </div>
      )}
      {picking && (
        <MovePicker device={picking} hallId={hallId} rowId={rowId} onCancel={() => setPicking(null)}
          onPick={(to) => {
            const r = racks.find((x) => x.devices.some((d) => d.id === picking.id))!
            setConfirm({ device: picking, from: { rackId: r.id, rackName: r.name, position_u: picking.position_u, face: picking.face }, to })
            setPicking(null)
          }} />
      )}
      {place && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Place device">
          <DeviceForm
            title={`Place device in ${place.rack.name}`}
            locationText={`${place.rack.name} · RU ${place.position_u} · ${face === 'front' ? 'Front' : 'Rear'}`}
            submitLabel="Place device"
            initial={{ ...placementBody(place.profile), rack_id: place.rack.id, position_u: place.position_u, face }}
            profile={allProfiles.find((x) => x.id === place.profile.profileId) ?? null}
            onChangeProfile={() => { setChoosing({ rack: place.rack, position_u: place.position_u }); setPlace(null) }}
            onSubmit={async (v: DeviceCreate) => {
              await create.mutateAsync({ ...v, ...placementBody(place.profile), rack_id: place.rack.id, position_u: place.position_u, face })
              setToast({ text: `${v.host_name} placed at ${place.rack.name} RU${place.position_u}` })
              setPlace(null)
            }}
            onCancel={() => setPlace(null)}
          />
        </div>
      )}
      {choosing && (
        <ChooseProfileSheet
          context={`${choosing.rack.name} · RU ${choosing.position_u} · ${face === 'front' ? 'Front' : 'Rear'}`}
          onCancel={() => setChoosing(null)}
          onAddProfile={() => { setChoosing(null); setAdding(true) }}
          onPick={(pp) => { setPlace({ ...choosing, profile: pp }); setChoosing(null) }}
        />
      )}
      {adding && <AddProfileDialog onClose={() => setAdding(false)} />}
      {editing != null && editQuery.data && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Edit device">
          <DeviceForm
            device={editQuery.data} title={`Edit ${editQuery.data.host_name}`}
            onSubmit={async (v) => { await update.mutateAsync({ id: editing, body: v }); setEditing(null) }}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast.text}
          {toast.undo && <button type="button" onClick={undo}>Undo</button>}
        </div>
      )}
    </section>
  )
}

