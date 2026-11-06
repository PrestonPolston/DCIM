// Profiles screen (profiles.md §5) over GET /profiles, with publish (readiness), retire,
// new version (clone), front image upload and delete. Edit and adopt are not built here yet.
import { Link, useSearchParams } from 'react-router'
import { RACK_UNIT_WIDTHS, useCabinetProfiles } from '../api/cabinetProfiles'
import { CabinetStatusBadge } from './CabinetProfilePage'
import { filterCabinets } from '../lib/cabinetForm'
import { ASSET_LABEL, ASSET_TYPES, ORIENTATIONS, PROFILE_API, issueLabel, needsReview, profileTitle, useProfiles, variantOf, type ProfileFilters, type UiProfile } from '../api/profiles'
import { useCan } from '../auth/auth'
import AddProfileDialog from '../components/profiles/AddProfileDialog'
import BulkImageUpload from '../components/profiles/BulkImageUpload'
import ProfileThumb from '../components/profiles/ProfileThumb'
import ProfileRowActions from '../components/profiles/ProfileRowActions'
import { FallbackSymbols } from '../components/rowfront/FallbackFront'

const TYPES: [string, string][] = [['all', 'All'], ['device', 'Device'], ['cabinet', 'Cabinet']]
const dims = (w: number | null, d: number | null, h: number | null) => (w == null && d == null && h == null ? '—' : [w, d, h].map((v) => (v == null ? '—' : String(v))).join(' × '))

const TABS: [NonNullable<ProfileFilters['status']>, string][] = [['all', 'All'], ['published', 'Published'], ['draft', 'Draft'], ['retired', 'Retired']]

function StateBadge({ p }: { p: UiProfile }) {
  if (p.status === 'draft') return <span className="badge profile-draft">✎ Draft</span>
  if (p.status === 'retired') return <span className="badge profile-retired">⊘ Retired</span>
  if (p.status === 'published' && needsReview(p)) {
    return <span className="badge profile-review" title="Can't be used for new devices; existing devices are unaffected">⚠ Needs review · {p.usableIssues.map(issueLabel).join(', ')}</span>
  }
  if (p.status === 'published') return <span>Published</span>
  return <span className="hint">—</span>
}

export default function ProfilesPage() {
  const [params, setParams] = useSearchParams()
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v); else next.delete(k)
    setParams(next, { replace: true })
  }
  const status = (params.get('status') as ProfileFilters['status']) || 'all'
  const filters: ProfileFilters = { status, q: params.get('q') ?? '', assetType: params.get('asset_type') ?? undefined }
  const needsImage = params.get('needs_image') === '1'
  const review = params.get('review') === '1'
  const orientation = params.get('orientation')
  const { items, all, isPending, error } = useProfiles(filters)
  const bulk = params.get('bulk')
  const rows = items.filter((p) => (!needsImage || !p.frontImage) && (!review || needsReview(p)) && (!orientation || (orientation === 'none' ? !p.orientation : p.orientation === orientation)))
  const canCreate = useCan('deviceType.create')
  const isAdmin = useCan('cabinetProfile.write')
  const type = params.get('type') === 'device' || params.get('type') === 'cabinet' ? params.get('type')! : 'all'
  const deviceOnlyFilter = !!filters.assetType || needsImage || review || !!orientation
  const cab = useCabinetProfiles({ status: 'all' })
  const cabRows = type === 'device' || deviceOnlyFilter ? [] : filterCabinets(cab.data ?? [], status, filters.q ?? '')
  const devRows = type === 'cabinet' ? [] : rows
  const empty = devRows.length + cabRows.length === 0
  const adding = params.get('new') === '1' || params.get('new') === 'cabinet'
  return (
    <section>
      <FallbackSymbols />
      <div className="page-header">
        <h1>Profiles</h1>
        {canCreate && <button type="button" onClick={() => set('bulk', review ? 'rear' : '1')}>⇪ Upload images</button>}
        {canCreate && <button type="button" className="primary" onClick={() => set('new', '1')}>＋ Add profile</button>}
      </div>
      <div className="segmented" role="group" aria-label="Profile state">
        {TABS.map(([v, l]) => (
          <button key={v} type="button" aria-pressed={status === v} onClick={() => set('status', v === 'all' ? null : v)}>{l}</button>
        ))}
      </div>
      <div className="segmented cp-type-filter" role="group" aria-label="Profile type">
        {TYPES.map(([v, l]) => (
          <button key={v} type="button" aria-pressed={type === v} onClick={() => set('type', v === 'all' ? null : v)}>{l}</button>
        ))}
      </div>
      <p className="hint" role="note">Draft → Published → Retired. Only published profiles can be placed; publishing needs the Admin role.</p>
      <div className="filters">
        <input type="search" aria-label="Search profiles" placeholder="Make, model, profile" value={filters.q} onChange={(e) => set('q', e.target.value)} />
        {type !== 'cabinet' && <>
        <select aria-label="Asset type" value={filters.assetType ?? ''} onChange={(e) => set('asset_type', e.target.value || null)}>
          <option value="">All asset types</option>
          {ASSET_TYPES.map((a) => <option key={a} value={a}>{ASSET_LABEL[a]}</option>)}
        </select>
        <select aria-label="Orientation" value={orientation ?? ''} onChange={(e) => set('orientation', e.target.value || null)}>
          <option value="">Any orientation</option>
          {ORIENTATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          <option value="none">Not specified</option>
        </select>
        <label className="toggle"><input type="checkbox" checked={needsImage} onChange={(e) => set('needs_image', e.target.checked ? '1' : null)} /> ◇ Needs image</label>
        <label className="toggle"><input type="checkbox" checked={review} onChange={(e) => set('review', e.target.checked ? '1' : null)} /> ⚠ Needs review (rear image / orientation)</label>
        </>}
      </div>
      {type !== 'device' && cab.data && !deviceOnlyFilter && (
        <p className="hint" role="status" data-testid="cabinet-count">{cabRows.length === cab.data.length ? `${cab.data.length} cabinet profile${cab.data.length === 1 ? '' : 's'}` : `${cabRows.length} of ${cab.data.length} cabinet profiles`}</p>
      )}
      {type !== 'device' && deviceOnlyFilter && <p className="hint" role="note">Cabinet profiles are hidden while a device-only filter is on.</p>}
      {error && <p className="error" role="alert">{error.message}</p>}
      {cab.error && type !== 'device' && <p className="error" role="alert">Cabinet profiles: {cab.error.message}</p>}
      {isPending && type !== 'cabinet' ? <p>Loading…</p> : (
        <table className="table" aria-label="Profiles">
          <thead><tr><th>Img</th><th>Type</th><th>Profile</th><th>Asset type</th><th>U</th><th>W×D×H mm</th><th>Depth</th><th>Rack width</th><th>State</th><th>Devices</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
          <tbody>
            {empty ? <tr><td colSpan={11} className="empty">No profiles match.</td></tr> : <>{devRows.map((p) => (
              <tr key={p.id}>
                <td><ProfileThumb profile={p} /></td>
                <td>Device</td>
                <td>{profileTitle(p)}{variantOf(p) && <span className="hint"> · {variantOf(p)}</span>}{p.orientation && <> <span className="orient-badge">⇄ {ORIENTATIONS.find(([v]) => v === p.orientation)![1].toUpperCase()}</span></>}{p.version && p.version > 1 ? <span className="chip-v"> v{p.version}</span> : null}</td>
                <td>{ASSET_LABEL[p.assetType ?? 'unknown'] ?? p.assetType}</td>
                <td>{p.uHeight}</td>
                <td className="mono nowrap">{dims(p.widthMm, p.depthMm, p.heightMm)}</td>
                <td>{p.isFullDepth ? 'Full' : 'Half'}</td>
                <td>—</td>
                <td><StateBadge p={p} />{!p.frontImage && <span className="badge profile-needs-image" title="No front image"> ◇ Needs image</span>}</td>
                <td className="mono">{PROFILE_API.deviceCount && p.deviceCount != null ? p.deviceCount : '—'}</td>
                <td>
                  <ProfileRowActions p={p} />
                </td>
              </tr>
            ))}
            {cabRows.map((c) => (
              <tr key={`cab-${c.id}`} data-kind="cabinet">
                <td>{c.front_image ? <img className="cp-thumb" src={c.front_image.thumb_url} alt="" /> : <span className="hint" aria-hidden="true">▭</span>}</td>
                <td>Cabinet</td>
                <td><Link to={`/profiles/cabinet/${c.id}`}>{c.manufacturer} {c.model}</Link><span className="hint"> · {c.name}</span>{c.version > 1 ? <span className="chip-v"> v{c.version}</span> : null}</td>
                <td>Cabinet</td>
                <td>{c.u_height ?? '—'}</td>
                <td className="mono nowrap">{dims(c.width_mm, c.depth_mm, c.height_mm)}</td>
                <td>—</td>
                <td>{c.rack_unit_width ? RACK_UNIT_WIDTHS.find(([v]) => v === c.rack_unit_width)![1] : '—'}</td>
                <td><CabinetStatusBadge p={c} />{c.status === 'draft' && !c.readiness.ready && <span className="hint"> · {c.readiness.missing.length} missing</span>}</td>
                <td className="mono">{c.rack_count ?? '—'}</td>
                <td><Link className="button" to={`/profiles/cabinet/${c.id}`}>{isAdmin ? 'Edit' : 'View'}</Link></td>
              </tr>
            ))}</>}
          </tbody>
        </table>
      )}
      {bulk && canCreate && <BulkImageUpload profiles={all} preset={bulk === 'rear' ? 'rear' : null} onClose={() => set('bulk', null)} />}
      {adding && (
        <AddProfileDialog
          initial={{ manufacturer: params.get('manufacturer') ?? '', model: params.get('model') ?? '' }}
          kind={params.get('new') === 'cabinet' ? 'cabinet' : 'device'}
          onKindChange={(k) => set('new', k === 'cabinet' ? 'cabinet' : '1')}
          onClose={() => { const n = new URLSearchParams(params); ['new', 'manufacturer', 'model'].forEach((k) => n.delete(k)); setParams(n, { replace: true }) }}
        />
      )}
    </section>
  )
}
