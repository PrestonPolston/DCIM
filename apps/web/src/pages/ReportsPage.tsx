import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { devicesApi } from '../api/client'
import { useDevices } from '../api/devices'
import { rackPath, typeLabel, useLookups } from '../api/racks'
import type { Device, DeviceListParams } from '../api/types'
import NoSerialBadge from '../components/NoSerialBadge'
import NeedsProfileBlock from '../components/NeedsProfileBlock'
import { needsProfile } from '../lib/needsProfile'
import StatusBadge from '../components/StatusBadge'
import { filterEmptyColumn } from '../lib/csv'
import { STATUSES, statusLabel } from '../lib/status'
import { ID_INPUT } from '../lib/inputs'
import ConnectionsReport from '../components/reports/ConnectionsReport'
import { useConnections } from '../api/connections'

// Reports home + Devices report + Connections report (docs/design/reports.md).
const PAGE = 50
const MAX = 500

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export default function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const rackId = params.get('rack_id') ?? ''
  const typeId = params.get('device_type_id') ?? ''
  const placement = params.get('placement') ?? ''
  const serial = params.get('serial') ?? '' // '' | 'has' | 'none'
  const review = params.get('review') === '1'
  const report = params.get('report') ?? ''
  const connTotal = useConnections({ limit: 1 }).data?.total
  const q = params.get('q') ?? ''
  const offset = Number(params.get('offset') ?? 0)
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('offset' in patch)) next.delete('offset')
    setParams(next, { replace: true })
  }

  const filters: Omit<DeviceListParams, 'limit' | 'offset'> = {
    status: status || undefined,
    rack_id: rackId ? Number(rackId) : undefined,
    device_type_id: typeId ? Number(typeId) : undefined,
    unplaced: placement ? placement === 'unplaced' : undefined,
    q: q || undefined,
    // ?needs_review=true (Backend); also filtered here in case the server ignores it.
    needs_review: review ? true : undefined,
  }
  // The API has no serial filter yet (missing_serial is [backend]); for serial presets we fetch
  // up to 500 server-filtered rows and filter/paginate here.
  const serialMode = serial !== '' || review
  const query = useDevices({ ...filters, limit: serialMode ? MAX : PAGE, offset: serialMode ? 0 : offset })
  const all = query.data?.items ?? []
  const filtered = serialMode
    ? all.filter((d) => (serial === '' || (serial === 'none' ? !d.serial_number : !!d.serial_number)) && (!review || needsProfile(d)))
    : all
  const rows = serialMode ? filtered.slice(offset, offset + PAGE) : filtered
  const total = serialMode ? filtered.length : (query.data?.total ?? 0)
  const truncated = serialMode && (query.data?.total ?? 0) > MAX

  const missing = useDevices({ limit: MAX })
  const missingCount = (missing.data?.items ?? []).filter((d) => !d.serial_number && d.status !== 'decom').length
  const totalDevices = missing.data?.total ?? 0

  const { racks, rows: rowList, halls, sites, deviceTypes } = useLookups()
  const rackById = useMemo(() => new Map(racks.map((r) => [r.id, r])), [racks])
  const location = (d: Device) => {
    const r = d.rack_id != null ? rackById.get(d.rack_id) : undefined
    if (!r) return '— Unplaced'
    const t = deviceTypes.find((x) => x.id === d.device_type_id)
    const top = d.position_u != null ? d.position_u + (t?.u_height ?? 1) - 1 : null
    const ru = d.position_u == null ? '' : top && top !== d.position_u ? ` / RU${d.position_u}–${top}` : ` / RU${d.position_u}`
    return `${[rackPath(r, rowList, halls, sites), r.name].filter(Boolean).join(' / ')}${ru} / ${d.face === 'rear' ? 'R' : 'F'}`
  }

  const [exporting, setExporting] = useState<string | null>(null)
  async function exportCsv() {
    setExporting('Exporting…')
    try {
      let text = await devicesApi.exportCsv(filters)
      if (serial === 'none') text = filterEmptyColumn(text, 'serial_number')
      const date = new Date().toISOString().slice(0, 10)
      download(`devices_all_${date}.csv`, text)
      setExporting(null)
    } catch (e) {
      setExporting(e instanceof Error ? e.message : String(e))
    }
  }

  const preset = (p: 'all' | 'missing' | 'review') =>
    p === 'all' ? set({ serial: '', status: '', review: '' })
      : p === 'missing' ? set({ serial: 'none', status: '', review: '' })
        : set({ serial: '', status: '', review: '1' })

  return (
    <section>
      <div className="page-header"><h1>Reports</h1></div>
      <div className="report-cards">
        <div className="card">
          <strong>Devices</strong>
          <span>{totalDevices} devices</span>
          <span className="hint">{STATUSES.map((s) => `${statusLabel(s)} ${(missing.data?.items ?? []).filter((d) => d.status === s).length}`).join(' · ')}</span>
          <button type="button" onClick={() => preset('all')}>View →</button>
        </div>
        <div className="card">
          <strong>Missing serial</strong>
          <span><NoSerialBadge /> {missingCount}{totalDevices > MAX ? '+' : ''} without a serial</span>
          <button type="button" onClick={() => preset('missing')}>View →</button>
        </div>
        <div className="card">
          <strong>Connections</strong>
          <span>{connTotal ?? '…'} connections</span>
          <button type="button" onClick={() => set({ report: 'connections' })}>View →</button>
        </div>
      </div>

      {report === 'connections' ? (
        <>
          <h2 style={{ marginTop: 'var(--space-5)' }}>Connections report <button type="button" className="ghost" onClick={() => set({ report: '' })}>Devices report →</button></h2>
          <ConnectionsReport />
        </>
      ) : (
      <>
      <h2 style={{ marginTop: 'var(--space-5)' }}>Devices report</h2>
      <div className="filters" role="group" aria-label="Report filters">
        <input type="search" aria-label="Search hostname or serial" {...ID_INPUT} enterKeyHint="search" placeholder="Hostname or serial" defaultValue={q}
          onKeyDown={(e) => e.key === 'Enter' && set({ q: (e.target as HTMLInputElement).value.trim() })}
          onBlur={(e) => set({ q: e.target.value.trim() })} />
        <select aria-label="Status" value={status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
        </select>
        <select aria-label="Cabinet" value={rackId} onChange={(e) => set({ rack_id: e.target.value })}>
          <option value="">All cabinets</option>
          {racks.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select aria-label="Profile" value={typeId} onChange={(e) => set({ device_type_id: e.target.value })}>
          <option value="">All profiles</option>
          {deviceTypes.map((t) => <option key={t.id} value={t.id}>{typeLabel(t)}</option>)}
        </select>
        <select aria-label="Placement" value={placement} onChange={(e) => set({ placement: e.target.value })}>
          <option value="">Placed and unplaced</option>
          <option value="placed">Placed</option>
          <option value="unplaced">Unplaced</option>
        </select>
        <select aria-label="Serial" value={serial} onChange={(e) => set({ serial: e.target.value })}>
          <option value="">Any serial</option>
          <option value="has">Has serial</option>
          <option value="none">No serial</option>
        </select>
        <button type="button" className="primary" onClick={() => void exportCsv()}>Export CSV</button>
      </div>
      <p className="hint">
        Presets: <button type="button" className="ghost" onClick={() => preset('all')}>All devices</button>
        <button type="button" className="ghost" onClick={() => preset('missing')}>⚑ Missing serial</button>
        <button type="button" className="ghost" aria-pressed={review} onClick={() => preset('review')}>? Needs review</button>
      </p>
      {exporting && <p className="hint" role="status">{exporting}</p>}
      {truncated && <p className="banner">Serial filter covers the first {MAX} matching devices (the API has no serial filter yet).</p>}
      {query.error && <p className="error" role="alert">{query.error.message}</p>}
      {query.isPending ? (
        <p>Loading…</p>
      ) : (
        <table className="table" aria-label="Devices report">
          <thead>
            <tr><th>Hostname</th><th>Profile</th><th>Location</th><th>Status</th><th>Serial</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={5} className="empty">No devices match these filters.</td></tr>
            ) : rows.map((d) => (
              <tr key={d.id}>
                <td className="host"><Link to={d.rack_id ? `/cabinets/${d.rack_id}?device=${d.id}` : '/devices'}>{d.host_name}</Link></td>
                <td>{typeLabel(deviceTypes.find((t) => t.id === d.device_type_id)) || '—'}</td>
                <td className="col-rack">{location(d)}</td>
                <td><StatusBadge status={d.status} /></td>
                <td className="mono">{d.serial_number || <NoSerialBadge />}{needsProfile(d) && <> <NeedsProfileBlock reason={d.needs_review_reason} /></>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!query.isPending && (
        <div className="pager">
          <span className="hint">{total === 0 ? '0' : `${offset + 1}–${offset + rows.length}`} of {total}</span>
          <button disabled={offset === 0} onClick={() => set({ offset: String(Math.max(0, offset - PAGE)) })}>‹ Prev</button>
          <button disabled={offset + PAGE >= total} onClick={() => set({ offset: String(offset + PAGE) })}>Next ›</button>
        </div>
      )}
      </>
      )}
    </section>
  )
}
