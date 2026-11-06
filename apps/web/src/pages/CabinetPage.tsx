import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { devicesApi } from '../api/client'
import { toRowFrontDevice } from '../api/rowFront'
import DeviceSidePanel from '../components/rowfront/DeviceSidePanel'
import { useCreateDevice, useDevices, useUpdateDevice } from '../api/devices'
import { toElevationDevices, useDeviceTypes, useHallLayout, useRackElevation } from '../api/racks'
import type { Device, DeviceCreate, Face } from '../api/types'
import DeviceForm from '../components/DeviceForm'
import ProfilePalette from '../components/profiles/ProfilePalette'
import ChooseProfileSheet from '../components/profiles/ChooseProfileSheet'
import AddProfileDialog from '../components/profiles/AddProfileDialog'
import { placementBody, useProfiles, type PlacingProfile } from '../api/profiles'
import RackElevation, { type ElevationView } from '../components/rack/RackElevation'
import { STATUSES, statusLabel } from '../lib/status'
import { layoutHall } from '../lib/hallLayout'
import { rackU } from '../lib/rack'
import { useHallSettings } from '../components/floorplan/useHallSettings'
import { useCan } from '../auth/auth'


/**
 * What is being placed: a new device from a profile, or an existing unplaced device
 * (with its profile, chosen first when it has none). No typeless placement.
 */
type Placing =
  | { kind: 'profile'; profile: PlacingProfile }
  | { kind: 'device'; device: Device; h: number; full: boolean; profile?: PlacingProfile }
type Slot = { position_u: number; face: Face }

export default function CabinetPage() {
  const params = useParams()
  const id = Number(params.rackId)
  const hallId = params.hallId ? Number(params.hallId) : undefined
  const elevation = useRackElevation(id)
  const hall = useHallLayout(hallId)
  const types = useDeviceTypes().data?.items ?? []
  const canWrite = useCan('device.write')
  // Server-side: devices not in any cabinet. Those without a profile pick one first.
  const unplacedQuery = useDevices({ unplaced: true, limit: 500 })
  const unplaced = unplacedQuery.data?.items ?? []
  const unplacedTotal = unplacedQuery.data?.total ?? 0
  const create = useCreateDevice()
  const update = useUpdateDevice()
  const [placing, setPlacing] = useState<Placing | null>(null)
  const [target, setTarget] = useState<{ placing: Placing; slot: Slot } | null>(null)
  const [announce, setAnnounce] = useState('')
  const [choosing, setChoosing] = useState<{ slot?: Slot; device?: Device } | null>(null)
  const [adding, setAdding] = useState(false)
  const profiles = useProfiles({ status: 'all' }).all
  // Always opens on Front (= the aisle side), per floor-plan.md §7.
  const [view, setView] = useState<ElevationView>('front')
  const [hallSettings] = useHallSettings(hallId ?? 0)
  const derived = useMemo(() => {
    if (!hall.data) return null
    return layoutHall(hall.data.rows, hallSettings).cabinets.find((c) => c.rack.id === id) ?? null
  }, [hall.data, hallSettings, id])
  const [collapse, setCollapse] = useState(false)
  const dropped = useRef(false)
  // Selected device: ?device={id} (deep links from Search, the tree and Reports) or a tap on a device.
  const [search, setSearch] = useSearchParams()
  const selectedId = Number(search.get('device')) || null
  const selectDevice = (devId: number | null) => {
    const next = new URLSearchParams(search)
    if (devId) next.set('device', String(devId))
    else next.delete('device')
    setSearch(next, { replace: true })
  }
  const [editingId, setEditingId] = useState<number | null>(null)
  const editQuery = useQuery({ queryKey: ['devices', 'one', editingId], queryFn: () => devicesApi.get(editingId!), enabled: editingId != null })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPlacing(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (elevation.isPending) return <p>Loading…</p>
  if (elevation.error) return <p className="error" role="alert">{elevation.error.message}</p>
  const rack = elevation.data
  const devices = toElevationDevices(rack).map((d, i) => ({ ...d, front: toRowFrontDevice(rack.devices[i]) }))
  const row = hall.data?.rows.find((r) => r.id === rack.row_id)
  const facing = rack.effective_orientation ?? derived?.facing ?? null
  const views: { value: ElevationView; label: string }[] = [
    { value: 'front', label: facing ? 'Front (aisle)' : 'Front' },
    { value: 'rear', label: facing ? 'Rear (back of row)' : 'Rear' },
    { value: 'both', label: 'Both' },
  ]
  const selApi = selectedId ? rack.devices.find((d) => d.id === selectedId) : undefined
  const selDev = selApi ? toRowFrontDevice(selApi) : undefined
  const counts = STATUSES.map((s) => [s, rack.devices.filter((d) => d.status === s).length] as const)

  const candidate = placing && (placing.kind === 'profile'
    ? { height_u: placing.profile.uHeight, is_full_depth: placing.profile.isFullDepth }
    : { height_u: placing.h, is_full_depth: placing.full, excludeId: placing.device.id })
  const typeOf = (d: Device) => types.find((t) => t.id === d.device_type_id)

  function onPlace(slot: Slot) {
    if (!placing) return
    dropped.current = true
    setTarget({ placing, slot })
    setPlacing(null)
  }

  const dragProps = (p: Placing) => ({
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      dropped.current = false
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData('text/plain', p.kind === 'profile' ? `profile:${p.profile.profileId}` : `device:${p.device.id}`)
      setPlacing(p)
    },
    onDragEnd: () => !dropped.current && setPlacing(null),
    // Click / Enter alternative: select, then click a highlighted RU.
    onClick: () => setPlacing((cur) => (cur && JSON.stringify(cur) === JSON.stringify(p) ? null : p)),
  })
  const isPlacing = (p: Placing) => !!placing && JSON.stringify(placing) === JSON.stringify(p)

  // Tap-to-move: pick the device up, then tap a green RU (no drag needed).
  async function startMove(devId: number) {
    selectDevice(null)
    const d = await devicesApi.get(devId)
    const t = types.find((x) => x.id === d.device_type_id)
    if (t) setPlacing({ kind: 'device', device: d, h: t.u_height, full: t.is_full_depth })
  }

  async function save(values: DeviceCreate) {
    if (!target) return
    const prof = target.placing.kind === 'profile' ? target.placing.profile : target.placing.profile
    const body = { ...values, ...(prof ? placementBody(prof) : {}), rack_id: rack.id, position_u: target.slot.position_u, face: target.slot.face }
    if (target.placing.kind === 'profile') await create.mutateAsync(body)
    else await update.mutateAsync({ id: target.placing.device.id, body: { ...body } })
    setAnnounce(`${values.host_name} placed at RU ${target.slot.position_u} ${target.slot.face}`)
    setTarget(null)
  }

  const targetPlacing = target ? (target.placing.kind === 'profile' ? target.placing.profile : target.placing.profile) : undefined
  const targetProfile = targetPlacing ? profiles.find((x) => x.id === targetPlacing.profileId) ?? null : null

  const crumbs = (
    <span className="hint">
      {hall.data && <Link to={`/halls/${hall.data.id}`}>{hall.data.name}</Link>}
      {row && ` › ${row.name}`} · {rackU(rack)} RU
    </span>
  )

  return (
    <section>
      <div className="page-header">
        {hallId && <Link className="button ghost" to={`/halls/${hallId}`}>‹ Hall</Link>}
        <h1>Cabinet {rack.name}</h1>
        {facing && (
          <span className="facing" title={rack.effective_orientation ? 'From the API' : 'Default for this row side (hall layout setting)'}>
            front faces {facing} → center aisle
          </span>
        )}
        {crumbs}
      </div>
      <div className="filters">
        <div className="segmented" role="group" aria-label="Cabinet face">
          {views.map((v) => (
            <button key={v.value} type="button" aria-pressed={view === v.value} onClick={() => setView(v.value)}>
              {v.label}
            </button>
          ))}
        </div>
        <label className="toggle">
          <input type="checkbox" checked={collapse} onChange={(e) => setCollapse(e.target.checked)} /> Collapse empty
        </label>
      </div>
      <p className="visually-hidden" aria-live="polite">{announce}</p>
      {placing && (
        <p className="banner" role="status">
          Placing {placing.kind === 'profile' ? placing.profile.label : placing.device.host_name}: choose a green RU, or press Esc.{' '}
          <button type="button" onClick={() => setPlacing(null)}>Cancel</button>
        </p>
      )}
      <div className={`cabinet-view${selDev ? ' with-panel' : ''}`}>
        {canWrite ? (
        <aside className="palette" aria-label="Device palette">
          <div className="palette-profiles">
          <ProfilePalette
            selectedId={placing?.kind === 'profile' ? placing.profile.profileId : null}
            onPick={(pp) => setPlacing(pp ? { kind: 'profile', profile: pp } : null)}
            onDragStart={(pp) => { dropped.current = false; setPlacing({ kind: 'profile', profile: pp }) }}
            onDragEnd={() => !dropped.current && setPlacing(null)}
            onAddProfile={() => setAdding(true)}
          />
          </div>
          <h2>Unplaced devices</h2>
          {unplaced.length > 0 && <p className="hint">Tap a device, then tap a green RU.</p>}
          {unplaced.length === 0 && <p className="hint">None</p>}
          {unplaced.map((d) => {
            const t = typeOf(d)
            if (!t) {
              // No profile yet: Choose profile comes first (profiles.md §7).
              return (
                <button key={d.id} type="button" className="palette-item mono" onClick={() => setChoosing({ device: d })}>
                  {d.host_name} · <span className="hint">Choose profile…</span>
                </button>
              )
            }
            const p: Placing = { kind: 'device', device: d, h: t.u_height, full: t.is_full_depth }
            return (
              <button key={d.id} type="button" className="palette-item mono" aria-pressed={isPlacing(p)} {...dragProps(p)}>
                {d.host_name} · {t.u_height}U
              </button>
            )
          })}
          {unplacedTotal > 500 && <p className="hint">Showing the first 500 of {unplacedTotal}.</p>}
        </aside>
        ) : (
          <p className="hint" role="note">Read-only: placing and moving devices needs the Technician or Admin role.</p>
        )}
        <div className="cabinet-elevation">
          {canWrite && <p className="hint tap-hint">Tap an empty RU to add a device from a profile.</p>}
          <RackElevation name={rack.name} uHeight={rackU(rack)} devices={devices} view={view} collapseEmpty={collapse}
            placing={candidate} onPlace={onPlace}
            onEmptyClick={canWrite ? (slot) => setChoosing({ slot }) : undefined}
            selectedId={selectedId}
            onDeviceClick={(d) => selectDevice(d.id === selectedId ? null : d.id)} />
          <p className="hint">{counts.map(([s, n]) => `${n} ${statusLabel(s)}`).join(' · ')}</p>
        </div>
        {selDev && (
          <DeviceSidePanel device={selDev} rack={{ id: rack.id, name: rack.name, u_height: rackU(rack), pos_x: null, pos_y: null, effective_orientation: null, u_used: rack.u_used, u_free: rack.u_free, devices: [] }}
            canMove={canWrite} onClose={() => selectDevice(null)}
            onEdit={() => setEditingId(selDev.id)} onMove={() => void startMove(selDev.id)} />
        )}
      </div>
      {choosing && (
        <ChooseProfileSheet
          context={choosing.slot ? `${rack.name} · RU ${choosing.slot.position_u} · ${choosing.slot.face === 'front' ? 'Front' : 'Rear'}` : choosing.device?.host_name}
          onCancel={() => setChoosing(null)}
          onAddProfile={() => { setChoosing(null); setAdding(true) }}
          onPick={(pp) => {
            const c = choosing
            setChoosing(null)
            const p: Placing = c.device ? { kind: 'device', device: c.device, h: pp.uHeight, full: pp.isFullDepth, profile: pp } : { kind: 'profile', profile: pp }
            if (c.slot) setTarget({ placing: p, slot: c.slot })
            else setPlacing(p)
          }}
        />
      )}
      {editingId != null && editQuery.data && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Edit device">
          <DeviceForm key={editingId} device={editQuery.data}
            onSubmit={async (v) => { await update.mutateAsync({ id: editingId, body: v }); setEditingId(null) }}
            onCancel={() => setEditingId(null)} />
        </div>
      )}
      {adding && <AddProfileDialog onClose={() => setAdding(false)} />}
      {target && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Place device">
          <DeviceForm
            key={JSON.stringify(target)}
            title={`Place device in ${rack.name}`}
            locationText={`${rack.name} · RU ${target.slot.position_u} · ${target.slot.face === 'front' ? 'Front' : 'Rear'}`}
            submitLabel={target.placing.kind === 'profile' ? 'Place device' : 'Move device'}
            device={target.placing.kind === 'device' ? target.placing.device : undefined}
            profile={targetProfile}
            onChangeProfile={() => { setChoosing({ slot: target.slot, device: target.placing.kind === 'device' ? target.placing.device : undefined }); setTarget(null) }}
            initial={{ ...(targetPlacing ? placementBody(targetPlacing) : {}), rack_id: rack.id, ...target.slot }}
            onSubmit={save}
            onCancel={() => setTarget(null)}
          />
        </div>
      )}
    </section>
  )
}
