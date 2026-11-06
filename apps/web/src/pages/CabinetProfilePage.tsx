// Cabinet profile detail (admin-setup.md §5): header (name, status, version), Specs in mm with
// inches, publish checklist, History, and admin-only actions Edit · Publish · Clone · Retire · Un-retire · Delete.
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { CABINET_PROFILE_API, useCabinetHistory, DOOR_TYPES, RAIL_TYPES, RACK_UNIT_WIDTHS, useCabinetActions, useCabinetProfile, type CabinetProfile } from '../api/cabinetProfiles'
import { useCan } from '../auth/auth'
import CabinetProfileForm from '../components/profiles/CabinetProfileForm'
import { cabinetErrorView } from '../components/profiles/cabinetErrors'
import { cabinetTitle, missingSentence, profileChecklist } from '../lib/cabinetForm'
import { fmtIn } from '../lib/units'
import { formatApiDate } from '../lib/apiDate'
import { collapseHistory } from '../lib/cabinetHistory'

export function CabinetStatusBadge({ p }: { p: Pick<CabinetProfile, 'status'> }) {
  if (p.status === 'draft') return <span className="badge profile-draft">✎ Draft</span>
  if (p.status === 'retired') return <span className="badge profile-retired">⊘ Retired</span>
  return <span>Published</span>
}
const label = <T extends string,>(opts: [T, string][], v: T | null) => (v ? opts.find(([k]) => k === v)?.[1] ?? v : '—')
const mm = (v: number | null) => (v == null ? '—' : <>{v} mm <span className="hint">({fmtIn(v)})</span></>)
const when = formatApiDate

type Confirm = 'retire' | 'delete' | null

const HISTORY_PAGE = 20
/** Admins: GET /cabinet-profiles/{id}/history (collapsed). Others (403 there): a summary from the profile's own fields. */
function HistoryPanel({ p, admin }: { p: CabinetProfile; admin: boolean }) {
  const [limit, setLimit] = useState(HISTORY_PAGE)
  const h = useCabinetHistory(p.id, admin, limit)
  const summary = (
    <ul className="cp-history">
      {when(p.created_at) && <li>Created {when(p.created_at)}{p.created_by ? ` by ${p.created_by}` : ''}</li>}
      {when(p.published_at) && <li>Published {when(p.published_at)}{p.published_by ? ` by ${p.published_by}` : ''}</li>}
      {p.status === 'retired' && when(p.retired_at) && <li>Retired {when(p.retired_at)}{p.retired_by ? ` by ${p.retired_by}` : ''}</li>}
      {when(p.updated_at) && <li>Last changed {when(p.updated_at)}{p.updated_by ? ` by ${p.updated_by}` : ''}</li>}
    </ul>
  )
  if (!admin) return <>{summary}<p className="hint">The full change log is visible to admins.</p></>
  if (h.isPending) return <p className="hint">Loading history…</p>
  if (h.error) return <>{summary}<p className="hint" role="note">Couldn't load the change log: {h.error.message}</p></>
  const entries = collapseHistory(h.data.items)
  return (
    <>
      <ol className="cp-history" aria-label="Change log">
        {entries.map((e) => (
          <li key={e.id}>
            <strong>{e.title}</strong> <span className="hint">{when(e.at)}{e.actor ? ` · ${e.actor}` : ''}</span>
            {e.changes.length > 0 && (
              <ul className="cp-changes">
                {e.changes.slice(0, 8).map((c) => <li key={c.field}>{c.label}: {e.title === 'Created' ? c.to : <>{c.from} → {c.to}</>}</li>)}
                {e.changes.length > 8 && <li className="hint">+{e.changes.length - 8} more</li>}
              </ul>
            )}
          </li>
        ))}
      </ol>
      {h.data.total > h.data.items.length && (
        <button type="button" className="ghost" onClick={() => setLimit((l) => l + HISTORY_PAGE)}>Show older ({h.data.total - h.data.items.length} more events)</button>
      )}
    </>
  )
}

export default function CabinetProfilePage() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const { data: p, isPending, error, refetch } = useCabinetProfile(Number.isFinite(id) ? id : null)
  const isAdmin = useCan('cabinetProfile.write')
  const actions = useCabinetActions()
  const [editing, setEditing] = useState(false)
  const [confirm, setConfirm] = useState<Confirm>(null)
  const [actionError, setActionError] = useState<ReactNode>(null)
  const [status, setStatus] = useState<string | null>(null)

  if (isPending) return <p>Loading…</p>
  if (error || !p) return <section><p className="error" role="alert">{error?.message ?? 'Cabinet profile not found.'}</p><Link to="/profiles?type=cabinet">← Profiles</Link></section>

  async function act(f: () => Promise<unknown>, done: string) {
    setActionError(null); setStatus(null)
    try { await f(); setStatus(done); setConfirm(null) } catch (e) { const v = cabinetErrorView(e, 'change', { title: cabinetTitle(p!), status: p!.status }); setActionError(<>{v.message}{v.node?.({ focusVariant: () => {}, reload: () => void refetch() })}</>); setConfirm(null) }
  }
  const items = profileChecklist(p)
  const spec: [string, ReactNode][] = [
    ['U height', p.u_height == null ? '—' : `${p.u_height} U`],
    ['Outer width', mm(p.width_mm)], ['Outer depth', mm(p.depth_mm)], ['Outer height', mm(p.height_mm)],
    ['Rack-unit width', label(RACK_UNIT_WIDTHS, p.rack_unit_width)],
    ['Front door', label(DOOR_TYPES, p.front_door)], ['Rear door', label(DOOR_TYPES, p.rear_door)],
    ['Rails', <>{label(RAIL_TYPES, p.rail_type)}{(p.rail_depth_min_mm != null || p.rail_depth_max_mm != null) && <> · {p.rail_depth_min_mm ?? '—'}–{p.rail_depth_max_mm ?? '—'} mm</>}</>],
    ['Usable width', mm(p.usable_width_mm)], ['Usable depth', mm(p.usable_depth_mm)],
    ['Weight capacity', p.weight_capacity_kg == null ? '—' : `${p.weight_capacity_kg} kg`],
    ['Colour', p.color_hex ? <><span className="cp-swatch" style={{ background: p.color_hex }} aria-hidden="true" /> {p.color_hex}</> : '—'],
    ['Racks using it', p.rack_count ?? '—'],
    ['Supersedes', p.supersedes_cabinet_profile_id == null ? '—' : <Link to={`/profiles/cabinet/${p.supersedes_cabinet_profile_id}`}>Profile #{p.supersedes_cabinet_profile_id}</Link>],
  ]
  return (
    <section className="cp-detail">
      <p><Link to="/profiles?type=cabinet">← Profiles</Link></p>
      <div className="page-header">
        <h1>{cabinetTitle(p)}</h1>
        <CabinetStatusBadge p={p} />
        <span className="chip-v">v{p.version}</span>
        <span className="hint">Cabinet profile</span>
      </div>
      {isAdmin ? (
        <div className="actions cp-actions" role="toolbar" aria-label="Profile actions">
          {p.status !== 'retired' && <button type="button" onClick={() => setEditing(true)}>Edit</button>}
          {p.status === 'draft' && <button type="button" className="primary" disabled={!p.readiness.ready || actions.busy}
            title={p.readiness.ready ? undefined : missingSentence(items)} onClick={() => void act(() => actions.publish(p.id), 'Published.')}>Publish</button>}
          <button type="button" disabled={actions.busy} onClick={() => void act(async () => { const c = await actions.clone(p.id); nav(`/profiles/cabinet/${c.id}`) }, 'Cloned as a new draft.')}>Clone</button>
          {p.status === 'published' && <button type="button" onClick={() => setConfirm('retire')}>Retire</button>}
          {p.status === 'retired' && CABINET_PROFILE_API.unretire && (
            <button type="button" className="primary" disabled={actions.busy} onClick={() => void act(() => actions.unretire(p.id), "Un-retired. It's offered for new cabinets again.")}>Un-retire</button>
          )}
          <button type="button" className="danger" onClick={() => setConfirm('delete')}>Delete</button>
        </div>
      ) : <p className="hint" role="note">View only. Cabinet profiles are managed by admins.</p>}
      {confirm === 'retire' && (
        <div className="banner" role="alertdialog" aria-label="Retire profile?">
          <strong>Retire {cabinetTitle(p)}?</strong> Profiles in use keep working; it won't be offered for new ones.
          <div className="actions"><button type="button" onClick={() => setConfirm(null)}>Cancel</button>
            <button type="button" className="primary" onClick={() => void act(() => actions.retire(p.id), 'Retired.')}>Retire</button></div>
        </div>
      )}
      {confirm === 'delete' && (
        <div className="banner" role="alertdialog" aria-label="Delete profile?">
          <strong>Delete {cabinetTitle(p)}?</strong> This can't be undone.
          <div className="actions"><button type="button" onClick={() => setConfirm(null)}>Cancel</button>
            <button type="button" className="danger solid" onClick={() => void act(async () => { await actions.remove(p.id); nav('/profiles?type=cabinet', { replace: true }) }, 'Deleted.')}>Delete</button></div>
        </div>
      )}
      <div role="alert" className="cp-error">{actionError && <p className="field-error">{actionError}</p>}</div>
      <p role="status" className="visually-hidden-when-empty">{status ?? ''}</p>
      <div className="cp-grid">
        <div className="card">
          <h2>Specs</h2>
          <dl className="cp-specs">{spec.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
          {p.notes && <><h3>Notes</h3><p>{p.notes}</p></>}
          {(p.front_image || p.rear_image) && (
            <div className="cp-images">
              {p.front_image && <figure><img src={p.front_image.thumb_url} alt="Front" /><figcaption>Front</figcaption></figure>}
              {p.rear_image && <figure><img src={p.rear_image.thumb_url} alt="Rear" /><figcaption>Rear</figcaption></figure>}
            </div>
          )}
        </div>
        <aside className="card">
          <h2>Publish checklist</h2>
          <ul className="checklist" aria-label="Publish checklist">
            {items.map((i) => <li key={i.key} className={i.ok ? 'ok' : 'bad'}><span aria-hidden="true">{i.ok ? '✓' : '✗'}</span> {i.label}<span className="visually-hidden">{i.ok ? ': done' : ': missing'}</span></li>)}
          </ul>
          <p className="hint" aria-live="polite">{p.status === 'draft' ? missingSentence(items) : p.status === 'published' ? 'Published.' : 'Retired: not offered for new cabinets.'}</p>
          <p className="hint">Images optional.</p>
          <h2>History</h2>
          <HistoryPanel p={p} admin={isAdmin} />
        </aside>
      </div>
      {editing && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Edit cabinet profile">
          <div className="card add-profile">
            <div className="form-header"><h2>Edit {cabinetTitle(p)}</h2>
              <button type="button" className="ghost icon" aria-label="Close" onClick={() => setEditing(false)}>✕</button></div>
            <CabinetProfileForm profile={p} mapError={(e, ctx) => cabinetErrorView(e, 'change', { ...ctx, status: p.status })} onClose={() => setEditing(false)} onReload={() => { void refetch(); setEditing(false) }} />
          </div>
        </div>
      )}
    </section>
  )
}
