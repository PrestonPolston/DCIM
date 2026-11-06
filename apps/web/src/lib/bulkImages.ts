// Bulk profile-image matching (ROW_3D_SPIKE.md §9). Pure: filenames/manifest → preview rows.
// Convention: <manufacturer>_<model>[_<variant>]_<front|rear>.<ext> (rear also "back");
// separators _ - space are interchangeable and case is ignored. A manifest.csv
// (filename,profile_id,face) overrides the filename match.
export type Face = 'front' | 'rear'
export interface MatchProfile { id: number; deviceTypeId: number; manufacturer: string; model: string; name: string; isDefault: boolean; uHeight: number }
export interface MatchRow { file: string; face: Face | null; profileId: number | null; error: string | null }

export const norm = (s: string) => s.toLowerCase().replace(/\.[a-z0-9]+$/, '').replace(/[\s_\-.]+/g, '')

export function parseName(file: string): { stem: string; face: Face | null } {
  const base = file.replace(/^.*[\\/]/, '').replace(/\.[A-Za-z0-9]+$/, '')
  const m = base.match(/^(.*?)[\s_\-.]*(front|rear|back)$/i)
  if (!m) return { stem: base, face: null }
  return { stem: m[1], face: m[2].toLowerCase() === 'front' ? 'front' : 'rear' }
}

export function parseManifest(csv: string): Map<string, { profileId: number; face: Face }> {
  const out = new Map<string, { profileId: number; face: Face }>()
  const lines = csv.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  const head = lines[0]?.toLowerCase().split(',').map((h) => h.trim()) ?? []
  const fi = head.indexOf('filename'), pi = head.indexOf('profile_id'), ci = head.indexOf('face')
  if (fi < 0 || pi < 0 || ci < 0) return out
  for (const l of lines.slice(1)) {
    const c = l.split(',').map((x) => x.trim())
    const face = c[ci]?.toLowerCase() === 'front' ? 'front' : c[ci]?.toLowerCase() === 'rear' || c[ci]?.toLowerCase() === 'back' ? 'rear' : null
    const id = Number(c[pi])
    if (c[fi] && face && Number.isInteger(id)) out.set(c[fi].toLowerCase(), { profileId: id, face })
  }
  return out
}

/** Match each file to one profile + face; flag no match, ambiguity and duplicates. */
export function matchFiles(files: string[], profiles: MatchProfile[], manifest?: Map<string, { profileId: number; face: Face }>): MatchRow[] {
  const byModel = new Map<string, MatchProfile[]>()
  const byVariant = new Map<string, MatchProfile>()
  for (const p of profiles) {
    const k = norm(`${p.manufacturer}${p.model}`)
    byModel.set(k, [...(byModel.get(k) ?? []), p])
    byVariant.set(norm(`${p.manufacturer}${p.model}${p.name}`), p)
  }
  const ids = new Set(profiles.map((p) => p.id))
  const seen = new Set<string>()
  return files.map((file) => {
    const fromManifest = manifest?.get(file.toLowerCase())
    let row: MatchRow
    if (fromManifest) {
      row = { file, face: fromManifest.face, profileId: ids.has(fromManifest.profileId) ? fromManifest.profileId : null, error: ids.has(fromManifest.profileId) ? null : `Manifest profile ${fromManifest.profileId} not found` }
    } else {
      const { stem, face } = parseName(file)
      const k = norm(stem)
      const exact = byVariant.get(k)
      const models = byModel.get(k) ?? []
      const pick = exact ?? (models.length === 1 ? models[0] : models.find((p) => p.isDefault))
      row = {
        file, face, profileId: pick?.id ?? null,
        error: !face ? 'Name must end in _front or _rear' : pick ? null : models.length > 1 ? 'Several profiles match: add the variant name' : 'No matching profile',
      }
    }
    if (row.profileId != null && row.face) {
      const key = `${row.profileId}:${row.face}`
      if (seen.has(key)) row = { ...row, error: 'Duplicate: another file has this profile and face' }
      seen.add(key)
    }
    return row
  })
}

/** Run tasks with a concurrency cap (3 for uploads); resolves when all settle. */
export async function runQueue<T>(items: T[], limit: number, worker: (item: T, index: number) => Promise<void>): Promise<void> {
  let next = 0
  const lane = async () => { while (next < items.length) { const i = next++; await worker(items[i], i).catch(() => {}) } }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane))
}

/** Expected filename for a profile face (shown in the "Needs rear image" preset). */
export const expectedName = (p: MatchProfile, face: Face) =>
  `${p.manufacturer}_${p.model}${p.isDefault ? '' : `_${p.name}`}_${face}.jpg`.replace(/\s+/g, '-')
