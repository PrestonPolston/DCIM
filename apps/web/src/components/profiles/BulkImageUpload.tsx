// Bulk upload of front/rear photos for the profile library (ROW_3D_SPIKE.md §9).
// Drop many files → match by filename (or manifest.csv) → preview with aspect checks →
// upload via the existing raw-body PUT …/images/{face}, 3 at a time, per-file retry.
import { useMemo, useState, type DragEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { HEIC_TEXT, isHeic, issueLabel, needsReview, profileKeys, profileTitle, uploadProfileImage, type UiProfile } from '../../api/profiles'
import { aspectWarning } from '../../lib/aspect'
import { expectedName, matchFiles, parseManifest, runQueue, type Face, type MatchProfile } from '../../lib/bulkImages'
import { prepareImage } from './prepareImage'

type State = 'ready' | 'uploading' | 'done' | 'failed' | 'skipped'
interface Row { file: File; profileId: number | null; face: Face | null; error: string | null; warn: string | null; px: string; state: State; msg?: string }

const CONCURRENCY = 3

export default function BulkImageUpload({ profiles, preset, onClose }: { profiles: UiProfile[]; preset: 'rear' | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [rows, setRows] = useState<Row[]>([])
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const usableTargets = profiles.filter((p) => p.status !== 'retired')
  const mp: MatchProfile[] = useMemo(() => usableTargets.map((p) => ({ id: p.id, deviceTypeId: p.deviceTypeId, manufacturer: p.manufacturer, model: p.model, name: p.name, isDefault: p.isDefault, uHeight: p.uHeight })), [usableTargets])
  const byId = new Map(usableTargets.map((p) => [p.id, p]))
  const needRear = profiles.filter((p) => needsReview(p) && p.usableIssues.includes('rear_image_missing'))

  async function take(list: FileList | File[]) {
    const all = [...list]
    const manifestFile = all.find((f) => /\.csv$/i.test(f.name))
    const manifest = manifestFile ? parseManifest(await manifestFile.text()) : undefined
    const images = all.filter((f) => f !== manifestFile)
    const matched = matchFiles(images.map((f) => f.name), mp, manifest)
    const next: Row[] = await Promise.all(images.map(async (file, i) => {
      const m = matched[i]
      let px = '', warn: string | null = null
      try {
        const bmp = typeof createImageBitmap === 'function' && !isHeic(file) ? await createImageBitmap(file) : null
        if (bmp) {
          px = `${bmp.width} × ${bmp.height}`
          const p = m.profileId != null ? byId.get(m.profileId) : undefined
          if (p) warn = aspectWarning(bmp.width, bmp.height, p.uHeight)
          bmp.close?.()
        }
      } catch { /* undecodable: the PUT will say why */ }
      return { file, profileId: m.profileId, face: m.face, error: isHeic(file) ? HEIC_TEXT : m.error, warn, px, state: 'ready' as State }
    }))
    setRows((r) => [...r, ...next])
  }

  const patch = (i: number, p: Partial<Row>) => setRows((r) => r.map((x, k) => (k === i ? { ...x, ...p } : x)))
  async function uploadOne(row: Row, i: number) {
    const p = row.profileId != null ? byId.get(row.profileId) : undefined
    if (!p || !row.face || row.error) { patch(i, { state: 'skipped' }); return }
    patch(i, { state: 'uploading', msg: undefined })
    try {
      const prep = await prepareImage(row.file)
      await uploadProfileImage(p.deviceTypeId, p.id, row.face, prep.blob)
      patch(i, { state: 'done', msg: prep.resized ? `Resized to ${prep.w} × ${prep.h}` : undefined })
    } catch (e) {
      patch(i, { state: 'failed', msg: e instanceof Error ? e.message : String(e) })
      throw e
    }
  }
  async function uploadAll(only?: number) {
    setBusy(true)
    const todo = rows.map((r, i) => ({ r, i })).filter(({ r, i }) => (only == null ? r.state === 'ready' || r.state === 'failed' : i === only))
    await runQueue(todo, CONCURRENCY, ({ r, i }) => uploadOne(r, i))
    await qc.invalidateQueries({ queryKey: profileKeys.all })
    setBusy(false)
  }

  const ok = rows.filter((r) => !r.error && r.profileId != null && r.face).length
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); void take(e.dataTransfer.files) }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Upload profile images">
      <div className="card form bulk-images">
        <div className="form-header">
          <button type="button" className="ghost icon" aria-label="Close" onClick={onClose} disabled={busy}>✕</button>
          <h2>Upload profile images</h2>
        </div>
        <p className="hint">Name files <code>Manufacturer_Model[_Variant]_front.jpg</code> / <code>_rear.jpg</code>, or add a <code>manifest.csv</code> (filename,profile_id,face). Front and rear are both required to publish. Photos are resized to ≤ 2048 px and uploaded 3 at a time.</p>
        {preset === 'rear' && (
          <div className="banner" role="note">
            <strong>Needs rear image:</strong> {needRear.length === 0 ? 'none — every published profile has a rear image.' : `${needRear.length} published profile(s) can't be used for new devices until a rear photo is added.`}
            {needRear.length > 0 && <ul className="bulk-expected">{needRear.map((p) => <li key={p.id}>{profileTitle(p)} · {p.name} → <code>{expectedName({ id: p.id, deviceTypeId: p.deviceTypeId, manufacturer: p.manufacturer, model: p.model, name: p.name, isDefault: p.isDefault, uHeight: p.uHeight }, 'rear')}</code> <span className="hint">({p.usableIssues.map(issueLabel).join(', ')})</span></li>)}</ul>}
          </div>
        )}
        <div className={`dropzone${over ? ' over' : ''}`} onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}>
          <label className="field">Choose files
            <input type="file" multiple aria-label="Choose image files" accept="image/png,image/jpeg,image/webp,image/heic,image/heif,.heic,.heif,.csv" onChange={(e) => { if (e.target.files) void take(e.target.files); e.target.value = '' }} />
          </label>
          <span className="hint">or drop images (and an optional manifest.csv) here</span>
        </div>
        {rows.length > 0 && (
          <table className="table" aria-label="Match preview">
            <thead><tr><th>File</th><th>Profile</th><th>Face</th><th>Pixels</th><th>Check</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.file.name}-${i}`}>
                  <td className="mono">{r.file.name}</td>
                  <td>
                    <select aria-label={`Profile for ${r.file.name}`} value={r.profileId ?? ''} disabled={busy || r.state === 'done'}
                      onChange={(e) => { const id = e.target.value ? Number(e.target.value) : null; patch(i, { profileId: id, error: id && r.face ? null : r.error, warn: null }) }}>
                      <option value="">— choose —</option>
                      {usableTargets.map((p) => <option key={p.id} value={p.id}>{profileTitle(p)} · {p.name}</option>)}
                    </select>
                  </td>
                  <td>
                    <select aria-label={`Face for ${r.file.name}`} value={r.face ?? ''} disabled={busy || r.state === 'done'}
                      onChange={(e) => { const f = (e.target.value || null) as Face | null; patch(i, { face: f, error: f && r.profileId ? null : r.error }) }}>
                      <option value="">—</option><option value="front">Front</option><option value="rear">Rear</option>
                    </select>
                  </td>
                  <td className="mono">{r.px || '—'}</td>
                  <td>{r.error ? <span className="field-error">{r.error}</span> : r.warn ? <span className="field-warn">⚠ {r.warn}</span> : '✓'}</td>
                  <td>
                    {r.state === 'ready' && 'Ready'}
                    {r.state === 'uploading' && 'Uploading…'}
                    {r.state === 'done' && <>✓ Uploaded{r.msg && <span className="hint"> · {r.msg}</span>}</>}
                    {r.state === 'skipped' && 'Skipped'}
                    {r.state === 'failed' && <><span className="field-error">✕ {r.msg}</span> <button type="button" onClick={() => void uploadAll(i)} disabled={busy}>Retry</button></>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="actions">
          <button type="button" className="primary" disabled={busy || ok === 0} onClick={() => void uploadAll()}>{busy ? 'Uploading…' : `Upload ${ok} image${ok === 1 ? '' : 's'}`}</button>
          <button type="button" onClick={onClose} disabled={busy}>Close</button>
        </div>
      </div>
    </div>
  )
}
