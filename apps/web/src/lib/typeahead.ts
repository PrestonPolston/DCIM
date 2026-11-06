// Free-text manufacturer/model typeahead (admin-setup.md §2): suggestions come from values already
// in use (device types + profiles) because GET /manufacturers and /models are Later in the plan.
// Any text is allowed; "Did you mean X?" only nudges toward an existing spelling.

/** Case, spacing and punctuation-insensitive key: "Hewlett-Packard " ≡ "hewlett packard". */
export const normKey = (s: string) => s.toLowerCase().normalize('NFKD').replace(/[^\p{L}\p{N}]+/gu, '')

/** Unique values (first spelling wins), sorted. */
export function uniqueValues(values: Iterable<string | null | undefined>): string[] {
  const seen = new Map<string, string>()
  for (const v of values) { const t = v?.trim(); if (t && !seen.has(t.toLowerCase())) seen.set(t.toLowerCase(), t) }
  return [...seen.values()].sort((a, b) => a.localeCompare(b))
}

/** Prefix matches first, then word-start, then substring; excludes an exact match. */
export function suggest(query: string, values: string[], limit = 8): string[] {
  const q = query.trim().toLowerCase()
  if (!q) return values.slice(0, limit)
  const rank = (v: string) => {
    const l = v.toLowerCase()
    if (l === q) return -1
    if (l.startsWith(q)) return 0
    if (l.split(/[\s\-_/.]+/).some((w) => w.startsWith(q))) return 1
    if (q.length >= 2 && (l.includes(q) || normKey(v).includes(normKey(q)))) return 2
    return -1
  }
  return values.map((v) => [v, rank(v)] as const).filter(([, r]) => r >= 0).sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0])).slice(0, limit).map(([v]) => v)
}

export function editDistance(a: string, b: string): number {
  if (a === b) return 0
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i++) {
    const cur = [i]
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    prev = cur
  }
  return prev[b.length]
}

/**
 * An existing value the typed one probably meant, or null when it matches exactly or nothing is close.
 * Close = same normalized key (case/space/punctuation), or ≤ 1 edit for 4–7 chars, ≤ 2 for 8+.
 */
export function didYouMean(value: string, values: string[]): string | null {
  const v = value.trim()
  if (!v || values.includes(v)) return null
  const k = normKey(v)
  if (!k) return null
  const same = values.find((x) => normKey(x) === k)
  if (same) return same
  const max = k.length >= 8 ? 2 : k.length >= 4 ? 1 : 0
  if (!max) return null
  let best: string | null = null, bestD = Infinity
  for (const x of values) {
    const d = editDistance(k, normKey(x))
    if (d <= max && d < bestD) { best = x; bestD = d }
  }
  return best
}
