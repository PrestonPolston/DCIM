import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useCreateDevice, useDevices, useUpdateDevice } from '../api/devices'
import { useLookups } from '../api/racks'
import type { Device, DeviceCreate } from '../api/types'
import DeviceForm from '../components/DeviceForm'
import StatusControl from '../components/StatusControl'
import NoSerialBadge from '../components/NoSerialBadge'
import NeedsProfileBlock from '../components/NeedsProfileBlock'
import { needsProfile } from '../lib/needsProfile'
import { STATUSES, statusLabel } from '../lib/status'
import { useCan } from '../auth/auth'
import { ID_INPUT } from '../lib/inputs'

type FormState = { mode: 'closed' } | { mode: 'create' } | { mode: 'edit'; device: Device }
const PAGE_SIZE = 50

export default function DevicesPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const rackFilter = params.get('rack_id') ?? ''
  const statusFilter = params.get('status') ?? ''
  const offset = Number(params.get('offset') ?? 0)

  // Debounce the search box before hitting the server-side q filter.
  const [qInput, setQInput] = useState(q)
  const [debouncedQ, setDebouncedQ] = useState(q)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(qInput.trim()), 250)
    return () => clearTimeout(t)
  }, [qInput])

  const devicesQuery = useDevices({
    q: debouncedQ || undefined,
    status: statusFilter || undefined,
    rack_id: rackFilter ? Number(rackFilter) : undefined,
    limit: PAGE_SIZE,
    offset,
  })
  const devices = devicesQuery.data?.items ?? []
  const total = devicesQuery.data?.total ?? 0
  const { racks, deviceTypes } = useLookups()
  const createDevice = useCreateDevice()
  const updateDevice = useUpdateDevice()
  const error = devicesQuery.error ? `Failed to load devices: ${devicesQuery.error.message}` : null
  const [form, setForm] = useState<FormState>({ mode: 'closed' })
  const canWrite = useCan('device.write')
  const canImport = useCan('device.import')

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'offset') next.delete('offset')
    setParams(next, { replace: true })
  }

  const rackName = (id?: number | null) => racks.find((r) => r.id === id)?.name
  const typeName = (id?: number | null) => deviceTypes.find((t) => t.id === id)?.name

  async function handleSubmit(values: DeviceCreate) {
    if (form.mode === 'edit') await updateDevice.mutateAsync({ id: form.device.id, body: values })
    else await createDevice.mutateAsync(values)
    setForm({ mode: 'closed' })
  }

  return (
    <section>
      <div className="page-header">
        <h1>Devices</h1>
        <div className="actions">
          {canImport && <Link className="button" to="/import">⤒ Import</Link>}
          {canWrite && <button className="primary" onClick={() => setForm({ mode: 'create' })}>Add device</button>}
        </div>
      </div>

      {form.mode !== 'closed' && (
        <DeviceForm
          key={form.mode === 'edit' ? form.device.id : 'new'}
          device={form.mode === 'edit' ? form.device : undefined}
          onSubmit={handleSubmit}
          onCancel={() => setForm({ mode: 'closed' })}
        />
      )}

      <div className="filters">
        <input type="search" placeholder="Hostname or serial…" aria-label="Search devices" {...ID_INPUT} enterKeyHint="search" value={qInput}
          onChange={(e) => { setQInput(e.target.value); setParam('q', e.target.value.trim()) }} />
        <select aria-label="Filter by cabinet" value={rackFilter} onChange={(e) => setParam('rack_id', e.target.value)}>
          <option value="">All cabinets</option>
          {racks.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select aria-label="Filter by status" value={statusFilter} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
        </select>
      </div>

      {!canWrite && <p className="hint" role="note">Your role is read-only: you can browse and export, but not change devices.</p>}
      {error && <p className="error" role="alert">{error}</p>}

      {devicesQuery.isPending ? (
        <p>Loading…</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Host name</th><th>Status</th><th>Serial Number</th><th>Cabinet</th><th>RU</th><th>Face</th><th>Profile</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {devices.length === 0 ? (
              <tr><td colSpan={8} className="empty">{total === 0 && !q && !statusFilter && !rackFilter ? 'No devices yet.' : 'No devices match your filters.'}</td></tr>
            ) : (
              devices.map((d) => (
                <tr key={d.id}>
                  <td className="host">{d.host_name}</td>
                  <td className="col-status"><StatusControl device={d} rackName={rackName(d.rack_id)} /></td>
                  <td className="mono">{d.serial_number || <NoSerialBadge />}{needsProfile(d) && <> <NeedsProfileBlock reason={d.needs_review_reason} /></>}</td>
                  <td className="col-rack">
                    {d.rack_id ? <Link to={`/cabinets/${d.rack_id}`}>{rackName(d.rack_id) ?? `#${d.rack_id}`}</Link> : (d.rack ?? '—')}
                  </td>
                  <td className="mono">{d.position_u ?? '—'}</td>
                  <td>{d.rack_id ? (d.face === 'rear' ? 'R' : 'F') : '—'}</td>
                  <td>{typeName(d.device_type_id) ?? '—'}</td>
                  <td className="row-actions">
                    {canWrite && <button onClick={() => setForm({ mode: 'edit', device: d })}>Edit</button>}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
      {!devicesQuery.isPending && (
        <div className="pager">
          <span className="hint">
            {total === 0 ? '0' : `${offset + 1}–${offset + devices.length}`} of {total}
          </span>
          <button disabled={offset === 0} onClick={() => setParam('offset', String(Math.max(0, offset - PAGE_SIZE)))}>‹ Prev</button>
          <button disabled={offset + PAGE_SIZE >= total} onClick={() => setParam('offset', String(offset + PAGE_SIZE))}>Next ›</button>
        </div>
      )}
    </section>
  )
}
