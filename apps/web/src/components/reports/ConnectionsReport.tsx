import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { CABLE_TYPES, connectionsApi, endLocation, useConnections, type ConnectionEnd, type ConnectionFilters } from '../../api/connections'
import { useLookups } from '../../api/racks'
import StatusBadge from '../StatusBadge'
import { STATUSES, statusLabel } from '../../lib/status'
import { ID_INPUT } from '../../lib/inputs'

const PAGE = 50

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

function End({ e }: { e: ConnectionEnd }) {
  const to = e.rack_id ? `/cabinets/${e.rack_id}?device=${e.device_id}` : `/search?q=${encodeURIComponent(e.host_name)}`
  return (
    <>
      <Link className="mono" to={to}>{e.host_name}</Link> <span className="mono">{e.port_name}</span>
      <br /><span className="hint">{endLocation(e)}</span>
    </>
  )
}

/** Connections report (docs/design/reports.md §2): filters, table, count, Export CSV. */
export default function ConnectionsReport() {
  const [params, setParams] = useSearchParams()
  const g = (k: string) => params.get(k) ?? ''
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) { if (v) next.set(k, v); else next.delete(k) }
    if (!('c_offset' in patch)) next.delete('c_offset')
    setParams(next, { replace: true })
  }
  const [qInput, setQInput] = useState(g('c_q'))
  useEffect(() => {
    const t = setTimeout(() => { if (qInput.trim() !== (params.get('c_q') ?? '')) set({ c_q: qInput.trim() }) }, 250)
    return () => clearTimeout(t)
  })
  const { halls, racks } = useLookups()
  const filters: ConnectionFilters = {
    hall_id: g('c_hall') ? Number(g('c_hall')) : undefined,
    rack_id: g('c_rack') ? Number(g('c_rack')) : undefined,
    cable_type: g('c_cable') || undefined,
    derived_status: g('c_status') || undefined,
    cross_cabinet: g('c_cross') === '1' || undefined,
    q: g('c_q') || undefined,
  }
  const offset = Number(g('c_offset') || 0)
  const query = useConnections({ ...filters, limit: PAGE, offset })
  const items = query.data?.items ?? []
  const total = query.data?.total ?? 0
  const [exportMsg, setExportMsg] = useState<string | null>(null)
  async function exportCsv() {
    setExportMsg('Exporting…')
    try {
      download(`connections_${new Date().toISOString().slice(0, 10)}.csv`, await connectionsApi.exportCsv(filters))
      setExportMsg(null)
    } catch (e) {
      setExportMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <section aria-label="Connections report">
      <div className="filters" role="group" aria-label="Connection filters">
        <input type="search" aria-label="Search host name, port or cable label" placeholder="Host name, port or cable label"
          value={qInput} onChange={(e) => setQInput(e.target.value)} {...ID_INPUT} enterKeyHint="search" />
        <select aria-label="Data Hall" value={g('c_hall')} onChange={(e) => set({ c_hall: e.target.value })}>
          <option value="">All halls</option>
          {halls.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
        </select>
        <select aria-label="Cabinet" value={g('c_rack')} onChange={(e) => set({ c_rack: e.target.value })}>
          <option value="">All cabinets</option>
          {racks.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select aria-label="Cable type" value={g('c_cable')} onChange={(e) => set({ c_cable: e.target.value })}>
          <option value="">All cable types</option>
          {CABLE_TYPES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select aria-label="Connection status" value={g('c_status')} onChange={(e) => set({ c_status: e.target.value })}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
        </select>
        <label className="toggle"><input type="checkbox" checked={g('c_cross') === '1'} onChange={(e) => set({ c_cross: e.target.checked ? '1' : '' })} /> Cross-cabinet only</label>
        <button type="button" onClick={() => void exportCsv()}>Export CSV</button>
      </div>
      {exportMsg && <p className="hint" role="status">{exportMsg}</p>}
      {query.error && <p className="error" role="alert">Failed to load connections: {query.error.message}</p>}
      <p className="hint" role="status">{total} connection{total === 1 ? '' : 's'}</p>
      <table className="table" aria-label="Connections">
        <thead><tr><th>A end</th><th>B end</th><th>Cable</th><th>Status</th></tr></thead>
        <tbody>
          {items.length === 0 ? (
            <tr><td colSpan={4} className="empty">{query.isPending ? 'Loading…' : 'No connections match.'}</td></tr>
          ) : items.map((c) => (
            <tr key={c.id}>
              <td><End e={c.a} /></td>
              <td><End e={c.b} /></td>
              <td className="mono">{c.cable ? [c.cable.label, c.cable.cable_type, c.cable.color, c.cable.length_m != null ? `${Number(c.cable.length_m)} m` : null].filter(Boolean).join(' · ') : '—'}</td>
              <td><StatusBadge status={c.derived_status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > PAGE && (
        <div className="pager">
          <span className="hint">{offset + 1}–{offset + items.length} of {total}</span>
          <button disabled={offset === 0} onClick={() => set({ c_offset: String(Math.max(0, offset - PAGE)) })}>‹ Prev</button>
          <button disabled={offset + PAGE >= total} onClick={() => set({ c_offset: String(offset + PAGE) })}>Next ›</button>
        </div>
      )}
    </section>
  )
}
