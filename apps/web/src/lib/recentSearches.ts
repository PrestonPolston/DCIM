// Recent searches (mobile.md §4a): last 10, newest first, in localStorage.
const KEY = 'dcim.search.recent'
const MAX = 10

export function loadRecent(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(0, MAX) : []
  } catch {
    return []
  }
}

export function pushRecent(q: string): string[] {
  const t = q.trim()
  if (t.length < 2) return loadRecent()
  const next = [t, ...loadRecent().filter((x) => x.toLowerCase() !== t.toLowerCase())].slice(0, MAX)
  try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* storage full or blocked */ }
  return next
}

export function clearRecent(): void {
  try { localStorage.removeItem(KEY) } catch { /* ignore */ }
}
