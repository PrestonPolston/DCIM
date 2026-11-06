// Profile palette (profiles.md §3): published profiles only; drag items carry a profile.
// Shared by the cabinet elevation, the row front view and the phone Choose profile sheet.
import { useState, type DragEvent } from 'react'
import { Link } from 'react-router'
import {
  ASSET_LABEL, ASSET_TYPES, ORIENTATIONS, PROFILE_API, PROFILE_MIME, issueLabel, placingOf, profileTitle, specLine, useProfiles, variantOf,
  type PlacingProfile, type ProfileFilters, type UiProfile,
} from '../../api/profiles'
import { useCan } from '../../auth/auth'
import ProfileThumb from './ProfileThumb'

interface Props {
  selectedId?: number | null
  onPick: (p: PlacingProfile | null) => void
  onDragStart?: (p: PlacingProfile) => void
  onDragEnd?: () => void
  onAddProfile?: () => void
  /** 'sheet' = full-width rows for the phone picker (no drag). */
  variant?: 'panel' | 'sheet'
  title?: string
}

export default function ProfilePalette({ selectedId, onPick, onDragStart, onDragEnd, onAddProfile, variant = 'panel', title = 'Profiles' }: Props) {
  const [f, setF] = useState<ProfileFilters>({})
  const { items, flagged, drafts, isPending, error } = useProfiles({ ...f, status: 'published' })
  const canCreate = useCan('deviceType.create')
  const chip = <K extends keyof ProfileFilters>(k: K, v: ProfileFilters[K], label: string) => (
    <button key={`${k}-${String(v)}`} type="button" className="chip" aria-pressed={f[k] === v} onClick={() => setF({ ...f, [k]: f[k] === v ? undefined : v })}>{label}</button>
  )
  const drag = (p: UiProfile) => (e: DragEvent) => {
    const pl = placingOf(p)
    e.dataTransfer.effectAllowed = 'copy'
    e.dataTransfer.setData(PROFILE_MIME, JSON.stringify(pl))
    e.dataTransfer.setData('text/plain', `profile:${p.id}`)
    onDragStart?.(pl)
  }
  return (
    <section className={`profile-palette pp-${variant}`} aria-label={title}>
      {variant === 'panel' && <h2>{title}</h2>}
      <input type="search" aria-label="Search profiles" placeholder="Make, model" value={f.q ?? ''} onChange={(e) => setF({ ...f, q: e.target.value })} />
      <div className="pp-chips" role="group" aria-label="Filters">
        {ASSET_TYPES.map((a) => chip('assetType', a, ASSET_LABEL[a]))}
        {chip('u', '1', '1U')}{chip('u', '2', '2U')}{chip('u', '4+', '4U+')}
        {chip('depth', 'full', 'Full')}{chip('depth', 'half', 'Half')}
      </div>
      {error && <p className="error" role="alert">{error.message}</p>}
      {isPending ? <p className="hint">Loading…</p> : items.length === 0 ? <p className="hint">No profiles match.</p> : (
        <ul className="pp-list">
          {items.map((p) => {
            const variantName = variantOf(p)
            return (
              <li key={p.id}>
                <button
                  type="button" className="pp-item" aria-pressed={selectedId === p.id}
                  aria-label={`${profileTitle(p)}${variantName ? ` · ${variantName}` : ''}, ${specLine(p)}`}
                  draggable={variant === 'panel'}
                  onDragStart={variant === 'panel' ? drag(p) : undefined}
                  onDragEnd={variant === 'panel' ? onDragEnd : undefined}
                  onClick={() => onPick(selectedId === p.id ? null : placingOf(p))}
                >
                  <ProfileThumb profile={p} />
                  <span className="pp-text">
                    <span className="pp-title">{profileTitle(p)}{p.version && p.version > 1 ? <span className="chip-v"> v{p.version}</span> : null}</span>
                    {variantName && <span className="hint">{variantName}</span>}
                    {p.orientation && <span className="orient-badge">⇄ {ORIENTATIONS.find(([v]) => v === p.orientation)![1].toUpperCase()}</span>}
                    <span className="hint">{specLine(p)} · {ASSET_LABEL[p.assetType ?? 'unknown'] ?? p.assetType}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {flagged.length > 0 && (
        <details className="pp-flagged">
          <summary>⚠ {flagged.length} need review (can't be placed)</summary>
          <ul className="pp-list">
            {flagged.map((p) => (
              <li key={p.id}>
                <button type="button" className="pp-item" disabled aria-disabled="true"
                  aria-label={`${profileTitle(p)}${variantOf(p) ? ` · ${variantOf(p)}` : ''}: ${p.usableIssues.map(issueLabel).join(', ')}`}>
                  <ProfileThumb profile={p} />
                  <span className="pp-text">
                    <span className="pp-title">{profileTitle(p)}</span>
                    <span className="hint">⚠ {p.usableIssues.map(issueLabel).join(', ')}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <Link to="/profiles?review=1">Fix in Profiles →</Link>
        </details>
      )}
      <div className="pp-footer">
        {canCreate && onAddProfile && <button type="button" className="ghost" onClick={onAddProfile}>＋ No profile? Add one</button>}
        {PROFILE_API.lifecycle && drafts > 0 && <Link to="/profiles?status=draft">✎ {drafts} drafts need finishing →</Link>}
      </div>
    </section>
  )
}
