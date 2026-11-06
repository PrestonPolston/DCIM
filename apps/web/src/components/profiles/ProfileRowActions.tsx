import { useRef, useState } from 'react'
import { ORIENTATIONS, PROFILE_API, imageProblem, missingFromError, missingText, orientationName, otherOrientation, profileTitle, useProfileActions, type Orientation, type UiProfile } from '../../api/profiles'
import { useCan } from '../../auth/auth'
import ConfirmDialog from '../ConfirmDialog'

type Pending = 'retire' | 'delete' | 'variant' | null
const oLabel = (o: Orientation) => ORIENTATIONS.find(([v]) => v === o)![1]

/** ⋯ menu on a profile row: Publish (readiness), Retire, New version, Upload front/rear image, Delete. */
export default function ProfileRowActions({ p }: { p: UiProfile }) {
  const admin = useCan('profile.publish')
  const canImage = useCan('deviceType.create')
  const a = useProfileActions()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending>(null)
  const file = useRef<HTMLInputElement>(null)
  const rear = useRef<HTMLInputElement>(null)
  const title = `${profileTitle(p)} · ${p.name}`

  async function run(f: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg(null)
    try { await f(); setMsg(ok); setPending(null) } catch (e) {
      const m = missingFromError(e)
      setMsg(m ? `Not ready to publish. Missing: ${missingText(m)}.` : e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  const ready = p.missing ? p.missing.length === 0 : null
  const [orient, setOrient] = useState<Orientation | ''>('')
  const [variantName, setVariantName] = useState('')
  const isSwitch = PROFILE_API.orientation && p.assetType === 'switch'
  // A NULL orientation may be filled any time (published + in use included); drafts by technicians too.
  const canOrient = isSwitch && !p.orientation && p.status !== 'retired' && (admin || (p.status === 'draft' && canImage))
  const canVariant = isSwitch && !!p.orientation && p.status !== 'retired' && admin

  return (
    <details className="row-menu">
      <summary aria-label={`Actions for ${profileTitle(p)} ${p.name}`}>⋯</summary>
      <div className="row-menu-body">
        {p.status === 'draft' && admin && (
          <>
            <button type="button" className="primary" disabled={busy || ready === false} onClick={() => void run(() => a.publish(p.id), `Published ${title}.`)}>Publish</button>
            {ready === false && <p className="hint">Missing: {missingText(p.missing!)}</p>}
          </>
        )}
        {p.status === 'published' && admin && (
          <>
            <button type="button" disabled={busy} onClick={() => void run(() => a.newVersion(p.id), `New draft version of ${title} created.`)}>New version</button>
            <button type="button" className="danger" disabled={busy} onClick={() => setPending('retire')}>Retire</button>
          </>
        )}
        {canImage && p.status !== 'retired' && (
          <>
            <button type="button" disabled={busy} onClick={() => file.current?.click()}>{p.frontImage ? 'Replace front image' : 'Upload front image'}</button>
            <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden aria-label={`Front image for ${title}`}
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (!f) return
                const bad = imageProblem(f)
                if (bad) { setMsg(bad); return }
                void run(() => a.upload(p, 'front', f), 'Front image uploaded.')
              }} />
            <button type="button" disabled={busy} onClick={() => rear.current?.click()}>{p.rearImage ? 'Replace rear image' : 'Upload rear image'}</button>
            <input ref={rear} type="file" accept="image/png,image/jpeg,image/webp" hidden aria-label={`Rear image for ${title}`}
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (!f) return
                const bad = imageProblem(f)
                if (bad) { setMsg(bad); return }
                void run(() => a.upload(p, 'rear', f), 'Rear image uploaded.')
              }} />
          </>
        )}
        {canOrient && (
          <div className="row-menu-orient">
            <select aria-label={`Orientation for ${title}`} value={orient} onChange={(e) => setOrient(e.target.value as Orientation | '')}>
              <option value="">Orientation…</option>
              {ORIENTATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <button type="button" disabled={busy || !orient} onClick={() => void run(() => a.setOrientation(p, orient as Orientation), `Orientation set to ${oLabel(orient as Orientation)}.`)}>Set orientation</button>
          </div>
        )}
        {canVariant && <button type="button" disabled={busy} onClick={() => { setVariantName(orientationName(p.model, otherOrientation(p.orientation!))); setPending('variant') }}>Add orientation variant</button>}
        {admin && p.deviceCount === 0 && <button type="button" className="danger" disabled={busy} onClick={() => setPending('delete')}>Delete</button>}
        {!admin && !canImage && <p className="hint">Read-only.</p>}
        <p className="hint">Edit and Move devices (adopt) aren't in this screen yet.</p>
        {msg && <p role="status">{msg}</p>}
      </div>
      {pending === 'retire' && (
        <ConfirmDialog title={`Retire ${title}?`} confirmLabel="Retire" danger busy={busy}
          onCancel={() => setPending(null)} onConfirm={() => void run(() => a.retire(p.id), `Retired ${title}.`)}>
          <p>Devices already on it keep it. It can't be used for new devices or placements, and can't be published again.</p>
        </ConfirmDialog>
      )}
      {pending === 'variant' && p.orientation && (
        <ConfirmDialog title={`Add orientation variant · ${profileTitle(p)}`} confirmLabel="Create draft" busy={busy}
          onCancel={() => setPending(null)} onConfirm={() => void run(() => a.orientationVariant(p.id, variantName), `Draft ${variantName} created (${oLabel(otherOrientation(p.orientation!))}).`)}>
          <p>Source: {p.name} ({oLabel(p.orientation)}) · {p.status === 'published' ? 'Published' : 'Draft'}</p>
          <p>New orientation: <strong>{oLabel(otherOrientation(p.orientation))}</strong></p>
          <label className="field">Name<input aria-label="Variant name" value={variantName} onChange={(e) => setVariantName(e.target.value)} /></label>
          <p className="hint">Swap from source: this profile's rear image becomes the new front and its front becomes the new rear. Fields are copied; the new draft still needs publishing.</p>
        </ConfirmDialog>
      )}
      {pending === 'delete' && (
        <ConfirmDialog title={`Delete ${title}?`} confirmLabel="Delete" danger busy={busy}
          onCancel={() => setPending(null)} onConfirm={() => void run(() => a.remove(p), `Deleted ${title}.`)}>
          <p>No devices use this profile.</p>
        </ConfirmDialog>
      )}
    </details>
  )
}
