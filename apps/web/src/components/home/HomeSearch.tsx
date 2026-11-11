import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { SEARCH_MIN, useHomeSearch, type HomeSearchHit, type SearchKind } from '../../api/home'

const GROUPS: [SearchKind, string, 'devices' | 'cabinets' | 'rows' | 'halls'][] = [
  ['device', 'Devices', 'devices'],
  ['cabinet', 'Cabinets', 'cabinets'],
  ['row', 'Rows', 'rows'],
  ['hall', 'Halls', 'halls'],
]

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  return !!t.closest('input, textarea, select, [contenteditable="true"]')
}

/** Header quick search: `/` focuses it. Fans out to device, cabinet, row and hall; DCREQ is parked. */
export default function HomeSearch() {
  const input = useRef<HTMLInputElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState('')
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setQ(value.trim()), 200)
    return () => clearTimeout(t)
  }, [value])
  const active = q.length >= SEARCH_MIN && open
  const results = useHomeSearch(q, active)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); input.current?.blur(); return }
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      if (isTypingTarget(e.target)) return
      e.preventDefault()
      input.current?.focus()
      setOpen(true)
    }
    const onClick = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [])

  const groups = GROUPS.map(([kind, label, key]) => ({ kind, label, items: (results.data?.[key] ?? []) as HomeSearchHit[] }))
  const hasAny = groups.some((g) => g.items.length > 0)
  const showPanel = open && value.trim().length > 0

  return (
    <div className="home-search" ref={wrap} role="search">
      <input
        ref={input}
        type="search"
        className="home-search-input"
        aria-label="Search device, cabinet, row or hall"
        placeholder="Search device, cabinet, row or hall  (/)"
        value={value}
        onChange={(e) => { setValue(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        autoComplete="off"
      />
      {showPanel && (
        <div className="home-search-panel" role="listbox" aria-label="Search results">
          {value.trim().length < SEARCH_MIN && <p className="hint">Type at least {SEARCH_MIN} characters.</p>}
          {active && results.isPending && <p className="hint">Searching…</p>}
          {active && results.error && <p className="error" role="alert">Couldn’t load search. <button type="button" className="link" onClick={() => void results.refetch()}>Retry</button></p>}
          {active && results.isSuccess && !hasAny && <p className="hint" role="status">No match.</p>}
          {active && results.isSuccess && groups.map((g) => g.items.length > 0 && (
            <div key={g.kind} className="home-search-group">
              <h2>{g.label}</h2>
              <ul>
                {g.items.map((hit) => (
                  <li key={`${hit.kind}-${hit.id}`}>
                    <Link role="option" to={hit.href} onClick={() => setOpen(false)}>
                      <span className="mono">{hit.label}</span>
                      {hit.subtitle && <span className="hint">{hit.subtitle}</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {active && results.isSuccess && results.data && (
            <div className="home-search-group">
              <h2>DCREQs</h2>
              <p className="hint" data-testid="dcreq-search-parked">Not available yet. {results.data.dcreqs.message}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
