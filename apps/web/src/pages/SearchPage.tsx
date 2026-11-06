import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useDevices } from '../api/devices'
import { useLookups } from '../api/racks'
import type { Device } from '../api/types'
import StatusBadge from '../components/StatusBadge'
import NoSerialBadge from '../components/NoSerialBadge'
import NeedsProfileBlock from '../components/NeedsProfileBlock'
import { needsProfile } from '../lib/needsProfile'
import { ID_INPUT } from '../lib/inputs'
import { clearRecent, loadRecent, pushRecent } from '../lib/recentSearches'

const MIN = 2
const LIMIT = 50

/** Search by host name or serial (mobile.md §4a): GET /devices?q= matches both. */
export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const urlQ = params.get('q') ?? ''
  const [input, setInput] = useState(urlQ)
  const [q, setQ] = useState(urlQ.trim())
  const [recent, setRecent] = useState(loadRecent)
  const { racks } = useLookups()

  useEffect(() => {
    const t = setTimeout(() => {
      const v = input.trim()
      setQ(v)
      const next = new URLSearchParams(params)
      if (v) next.set('q', v)
      else next.delete('q')
      if (next.toString() !== params.toString()) setParams(next, { replace: true })
    }, 250)
    return () => clearTimeout(t)
  }, [input, params, setParams])

  const active = q.length >= MIN
  const results = useDevices({ q, limit: LIMIT }, { enabled: active })
  const items = active ? results.data?.items ?? [] : []
  const total = active ? results.data?.total ?? 0 : 0
  const rackName = (id?: number | null) => racks.find((r) => r.id === id)?.name

  const remember = () => setRecent(pushRecent(q))
  const href = (d: Device) => (d.rack_id ? `/cabinets/${d.rack_id}?device=${d.id}` : `/devices?q=${encodeURIComponent(d.host_name)}`)
  const where = (d: Device) =>
    d.rack_id ? `${rackName(d.rack_id) ?? `#${d.rack_id}`} · RU${d.position_u ?? '?'} ${d.face === 'rear' ? 'R' : 'F'}` : 'Not in a cabinet'

  return (
    <section className="search-page">
      <h1 className="visually-hidden">Search</h1>
      <form role="search" className="search-bar" onSubmit={(e) => { e.preventDefault(); setQ(input.trim()); remember() }}>
        <input type="search" aria-label="Search host name or serial" placeholder="🔍 Host name or serial" autoFocus
          value={input} onChange={(e) => setInput(e.target.value)} {...ID_INPUT} enterKeyHint="search" className="mono" />
        {input && <button type="button" className="ghost icon" aria-label="Clear search" onClick={() => setInput('')}>✕</button>}
      </form>

      {!active && (
        <div className="recent">
          {input.trim().length === 1 && <p className="hint">Type at least {MIN} characters.</p>}
          {recent.length > 0 ? (
            <>
              <div className="recent-head">
                <h2>Recent searches</h2>
                <button type="button" className="ghost" onClick={() => { clearRecent(); setRecent([]) }}>Clear</button>
              </div>
              <ul className="recent-list">
                {recent.map((r) => (
                  <li key={r}><button type="button" className="ghost mono" onClick={() => setInput(r)}>{r}</button></li>
                ))}
              </ul>
            </>
          ) : (
            input.trim().length === 0 && <p className="hint">Find a device by host name or serial.</p>
          )}
        </div>
      )}

      {active && results.isPending && <p className="hint">Searching…</p>}
      {active && results.error && <p className="error" role="alert">Search failed: {results.error.message}</p>}
      {active && results.isSuccess && items.length === 0 && (
        <p className="empty" role="status">No match. Devices without a serial can only be found by host name.</p>
      )}
      {items.length > 0 && (
        <>
          <p className="hint" role="status">{total > items.length ? `First ${items.length} of ${total}` : `${total} found`}</p>
          <ul className="result-list">
            {items.map((d) => (
              <li key={d.id}>
                <Link className="result-card" to={href(d)} onClick={remember}>
                  <span className="rc-line1"><span className="mono rc-host">{d.host_name}</span> <StatusBadge status={d.status} /></span>
                  <span className="rc-line2 hint">{where(d)}</span>
                  <span className="rc-line3">
                    {d.serial_number ? <span className="mono">SN {d.serial_number}</span> : <NoSerialBadge note={(d as Device & { serial_note?: string | null }).serial_note} />}
                    {needsProfile(d) && <> <NeedsProfileBlock reason={d.needs_review_reason} /></>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
