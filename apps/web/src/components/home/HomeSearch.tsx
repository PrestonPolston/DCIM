import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  PARKED, SEARCH_DEFAULT_LIMIT, SEARCH_MAX_LIMIT, SEARCH_MIN,
  searchHref, searchSubtitle, useHomeSearch,
  type SearchGroup, type SearchGroupKey,
} from '../../api/home'

const GROUP_LABEL: Record<SearchGroupKey, string> = {
  devices: 'Devices',
  cabinets: 'Cabinets',
  rows: 'Rows',
  halls: 'Halls',
}

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  return !!t.closest('input, textarea, select, [contenteditable="true"]')
}

function groupOf(groups: SearchGroup[] | undefined, key: SearchGroupKey): SearchGroup | undefined {
  return groups?.find((g) => g.key === key)
}

/** Header quick search: `/` focuses it. GET /home/search; DCREQ is parked. */
export default function HomeSearch() {
  const input = useRef<HTMLInputElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState('')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState({ q: '', limit: SEARCH_DEFAULT_LIMIT })
  useEffect(() => {
    const t = setTimeout(() => {
      const next = value.trim()
      setQuery((prev) => prev.q === next ? prev : { q: next, limit: SEARCH_DEFAULT_LIMIT })
    }, 200)
    return () => clearTimeout(t)
  }, [value])
  const { q, limit } = query
  const active = q.length >= SEARCH_MIN && open
  const results = useHomeSearch(q, active, limit)

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

  const groups = (['devices', 'cabinets', 'rows', 'halls'] as const).map((key) => groupOf(results.data?.groups, key))
  const hasAny = groups.some((g) => (g?.items.length ?? 0) > 0)
  const parked = results.data?.parked ?? [PARKED.dcreq_search]
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
          {active && results.isSuccess && groups.map((g) => g && g.items.length > 0 && (
            <div key={g.key} className="home-search-group">
              <h2>{GROUP_LABEL[g.key]}</h2>
              <ul>
                {g.items.map((item) => {
                  const href = searchHref(g.key, item)
                  const subtitle = searchSubtitle(g.key, item)
                  const body = (
                    <>
                      <span className="mono">{item.label}</span>
                      {subtitle && <span className="hint">{subtitle}</span>}
                    </>
                  )
                  return (
                    <li key={`${g.key}-${item.id}`}>
                      {href
                        ? <Link role="option" to={href} onClick={() => setOpen(false)}>{body}</Link>
                        : <span role="option" aria-disabled="true">{body}</span>}
                    </li>
                  )
                })}
              </ul>
              {g.truncated && limit < SEARCH_MAX_LIMIT && (
                <button type="button" className="link home-search-show-all" onClick={() => setQuery((prev) => ({ ...prev, limit: SEARCH_MAX_LIMIT }))}>
                  Show all {g.count}
                </button>
              )}
              {g.truncated && limit >= SEARCH_MAX_LIMIT && (
                <p className="hint">Showing {g.items.length} of {g.count}.</p>
              )}
            </div>
          ))}
          {active && results.isSuccess && parked.map((tile) => (
            <div key={tile.key} className="home-search-group">
              <h2>DCREQs</h2>
              <p className="hint" data-testid="dcreq-search-parked">Not available yet. {tile.message}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
