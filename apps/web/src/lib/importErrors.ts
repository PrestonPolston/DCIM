// Classify CSV dry-run row errors (POST /devices/import). The API returns plain
// strings per row today (ImportRowError.errors: string[]), so profile errors are
// recognised by wording; switch to a code when rows carry `profile_required` (item 44).
export type RowErrorKind = 'profile_required' | 'other'

export function classifyRowError(msg: string): RowErrorKind {
  return /profile|unknown device type/i.test(msg) ? 'profile_required' : 'other'
}

/** Manufacturer / model for a CSV line (header = line 1), for the Create profile link. */
export function rowModel(rows: string[][], line: number): { manufacturer: string; model: string } {
  const header = rows[0]?.map((h) => h.trim().toLowerCase()) ?? []
  const r = rows[line - 1] ?? []
  const get = (k: string) => (header.indexOf(k) >= 0 ? (r[header.indexOf(k)] ?? '').trim() : '')
  return { manufacturer: get('manufacturer'), model: get('model') }
}
