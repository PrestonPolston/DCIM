// Side panel Move: Hall › Row › Cabinet → RU and face, for moves to another row (row-front.md §4).
import { useState } from 'react'
import { toElevationDevices, useHallLayout, useHalls, useRackElevation } from '../../api/racks'
import type { Face } from '../../api/types'
import { checkFit, type Spot } from '../../lib/placement'
import { rackU } from '../../lib/rack'
import { deviceU, toElevationDevice, type RowFrontDevice } from '../../lib/rowFront'
import { RU_INPUT } from '../../lib/inputs'

interface Props { device: RowFrontDevice; hallId: number; rowId: number; onCancel: () => void; onPick: (to: Spot) => void }

export default function MovePicker({ device, hallId, rowId, onCancel, onPick }: Props) {
  const halls = useHalls()
  const [h, setH] = useState(hallId)
  const layout = useHallLayout(h)
  const [r, setR] = useState<number | null>(rowId)
  const row = layout.data?.rows.find((x) => x.id === r)
  const [rackId, setRackId] = useState<number | null>(null)
  const rack = row?.racks.find((x) => x.id === rackId)
  const el = useRackElevation(rackId ?? 0, rackId != null)
  const [pos, setPos] = useState(device.position_u)
  const [face, setFace] = useState<Face>(device.face)
  const fit = rack && el.data ? checkFit(rackU(rack), toElevationDevices(el.data), toElevationDevice(device), pos, face) : null
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={`Move ${device.host_name}`}>
      <form className="card form" onSubmit={(e) => { e.preventDefault(); if (rack && fit?.ok) onPick({ rackId: rack.id, rackName: rack.name, position_u: pos, face }) }}>
        <h2>Move {device.host_name}</h2>
        <label className="field">Hall
          <select value={h} onChange={(e) => { setH(Number(e.target.value)); setR(null); setRackId(null) }}>
            {(halls.data?.items ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label className="field">Row
          <select value={r ?? ''} onChange={(e) => { setR(Number(e.target.value) || null); setRackId(null) }}>
            <option value="">Choose a row</option>
            {(layout.data?.rows ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label className="field">Cabinet
          <select value={rackId ?? ''} onChange={(e) => setRackId(Number(e.target.value) || null)} disabled={!row}>
            <option value="">Choose a cabinet</option>
            {(row?.racks ?? []).map((x) => <option key={x.id} value={x.id}>{x.name} · {x.u_free} free</option>)}
          </select>
        </label>
        <label className="field">Lowest RU ({deviceU(device)}U device)
          <input type="number" min={1} {...RU_INPUT} max={rack ? rackU(rack) : undefined} value={pos} onChange={(e) => setPos(Number(e.target.value))} />
        </label>
        <label className="field">Face
          <select value={face} onChange={(e) => setFace(e.target.value as Face)}>
            <option value="front">Front</option><option value="rear">Rear</option>
          </select>
        </label>
        {fit && !fit.ok && <p className="field-error" role="alert">Can't place: {fit.reason}</p>}
        <div className="actions">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="submit" className="primary" disabled={!fit?.ok}>Continue</button>
        </div>
      </form>
    </div>
  )
}
