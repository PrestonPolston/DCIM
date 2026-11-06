// Add profile (profiles.md §4): Save draft needs manufacturer, model and name;
// Publish shows the checklist (server missing[] is authoritative once it exists).
// Type Device · Cabinet (admin-setup.md §2): Cabinet is admin only; technicians never see the control.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ASSET_LABEL, ASSET_TYPES, MOUNTINGS, ORIENTATIONS, PROFILE_API, canSaveDraft, checklist, emptyProfileForm, findDuplicate,
  heightWarning, missingFromError, missingText, profileTitle, useProfileActions, useProfiles, useSaveProfileDraft, orientationName, type ProfileForm } from '../../api/profiles'
import { useCan } from '../../auth/auth'
import type { RowFrontDevice } from '../../lib/rowFront'
import DeviceFront from '../rowfront/DeviceFront'
import { FallbackSymbols } from '../rowfront/FallbackFront'
import ImageDropzone from './ImageDropzone'
import CabinetProfileForm, { type ErrorMapper } from './CabinetProfileForm'
import { cabinetErrorView } from './cabinetErrors'
import type { CabinetProfile } from '../../api/cabinetProfiles'
import { RU_INPUT } from '../../lib/inputs'
import { normKey, uniqueValues } from '../../lib/typeahead'
import Typeahead from './Typeahead'

const PREVIEW_RU = 44

export type ProfileKind = 'device' | 'cabinet'
export const ONLY_ADMINS_CABINET = 'Only admins can create cabinet profiles.'

export default function AddProfileDialog({ initial, onClose, onSaved, kind: initialKind = 'device', onKindChange, onCabinetSaved, cabinetErrors }: {
  initial?: Partial<ProfileForm>; onClose: () => void; onSaved?: (profileId: number) => void
  kind?: ProfileKind; onKindChange?: (k: ProfileKind) => void; onCabinetSaved?: (p: CabinetProfile) => void; cabinetErrors?: ErrorMapper
}) {
  const isAdmin = useCan('cabinetProfile.write')
  const [kind, setKind] = useState<ProfileKind>(initialKind)
  const pick = (k: ProfileKind) => { setKind(k); onKindChange?.(k) }
  const typeControl = isAdmin && (
    <div className="ap-type"><span id="ap-type-label">Type</span>
      <div className="segmented" role="group" aria-labelledby="ap-type-label">
        {(['device', 'cabinet'] as const).map((k) => <button key={k} type="button" aria-pressed={kind === k} onClick={() => pick(k)}>{k === 'device' ? 'Device' : 'Cabinet'}</button>)}
      </div>
    </div>
  )
  if (kind === 'cabinet') {
    return (
      <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="New cabinet profile">
        <div className="card add-profile">
          <div className="form-header">
            <h2>New cabinet profile · Draft</h2>
            <button type="button" className="ghost icon" aria-label="Close" onClick={onClose}>✕</button>
          </div>
          {typeControl}
          {isAdmin ? <CabinetProfileForm onClose={onClose} onSaved={onCabinetSaved} mapError={cabinetErrors ?? ((e, ctx) => cabinetErrorView(e, 'create', ctx))} />
            : <p className="field-error" role="alert">{ONLY_ADMINS_CABINET}</p>}
        </div>
      </div>
    )
  }
  return <DeviceProfileDialog initial={initial} onClose={onClose} onSaved={onSaved} typeControl={typeControl} />
}

function DeviceProfileDialog({ initial, onClose, onSaved, typeControl }: {
  initial?: Partial<ProfileForm>; onClose: () => void; onSaved?: (profileId: number) => void; typeControl: ReactNode
}) {
  const [f, setF] = useState<ProfileForm>(() => emptyProfileForm(initial))
  const set = (patch: Partial<ProfileForm>) => setF((cur) => ({ ...cur, ...patch }))
  const { all, types } = useProfiles({ status: 'all' })
  const save = useSaveProfileDraft()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const actions = useProfileActions()
  const canPublish = useCan('profile.publish')
  const [savedId, setSavedId] = useState<number | null>(null)
  const [serverMissing, setServerMissing] = useState<string[] | null>(null)
  const [published, setPublished] = useState(false)
  const items = checklist(f, serverMissing)
  const missing = items.filter((i) => !i.ok).length
  const dups = findDuplicate(f, all)
  const warn = heightWarning(f)
  // Typeahead options from values already in use (device types + profiles); free text is allowed.
  const manufacturers = useMemo(() => uniqueValues([...types.map((t) => t.manufacturer), ...all.map((p) => p.manufacturer)]), [types, all])
  const models = useMemo(() => {
    const k = normKey(f.manufacturer)
    const same = (m: string) => !k || normKey(m) === k
    return uniqueValues([...types.filter((t) => same(t.manufacturer)).map((t) => t.name), ...all.filter((p) => same(p.manufacturer)).map((p) => p.model)])
  }, [types, all, f.manufacturer])

  // Live preview: object URL for a chosen front image, else the generic face.
  const imgUrl = useMemo(
    () => (f.frontImage && typeof URL.createObjectURL === 'function' ? URL.createObjectURL(f.frontImage) : null),
    [f.frontImage],
  )
  useEffect(() => () => { if (imgUrl) URL.revokeObjectURL(imgUrl) }, [imgUrl])
  const u = Math.max(1, Math.min(8, Number(f.uHeight) || 1))
  const preview: RowFrontDevice = {
    id: -1, host_name: f.name || 'Preview', status: 'active', serial_number: 'preview', position_u: 1, top_u: u, face: 'front',
    device_type: { id: -1, manufacturer: f.manufacturer, name: f.model, u_height: u, is_full_depth: f.fullDepth, asset_type: f.assetType || null },
    effective_asset_type: f.assetType || null,
    effective_front_image: imgUrl ? { url: imgUrl, thumb_url: imgUrl } : null,
  }

  async function ensureSaved(): Promise<number> {
    if (savedId != null) return savedId
    const p = await save(f, types)
    setSavedId(p.id)
    setSaved(`Saved draft ${f.manufacturer.trim()} ${f.model.trim()} · ${p.name}.`)
    onSaved?.(p.id)
    return p.id
  }
  async function saveDraft() {
    setBusy(true); setError(null)
    try {
      await ensureSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }
  async function publish() {
    setBusy(true); setError(null)
    try {
      const id = await ensureSaved()
      await actions.publish(id)
      setServerMissing([])
      setPublished(true)
      setSaved(`Published ${f.manufacturer.trim()} ${f.model.trim()} · ${f.name.trim()}. It can now be placed.`)
    } catch (e) {
      const m = missingFromError(e)
      if (m) { setServerMissing(m); setError(`Not ready to publish. Missing: ${missingText(m)}.`) }
      else setError(e instanceof Error ? e.message : 'Publish failed')
    } finally {
      setBusy(false)
    }
  }

  const num = (k: keyof ProfileForm, label: string) => (
    <label className="field">{label}
      <input type="number" inputMode="decimal" min={0} step="0.1" aria-label={label} value={f[k] as string} onChange={(e) => set({ [k]: e.target.value } as Partial<ProfileForm>)} />
    </label>
  )

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="New profile">
      <div className="card add-profile">
        <FallbackSymbols />
        <div className="form-header">
          <h2>New profile · Draft</h2>
          <button type="button" className="ghost icon" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {typeControl}
        <div className="ap-grid">
          <form className="form" onSubmit={(e) => { e.preventDefault(); if (canSaveDraft(f)) void saveDraft() }}>
            <fieldset><legend>Model</legend>
              <Typeahead label="Manufacturer" required value={f.manufacturer} options={manufacturers} onChange={(v) => set({ manufacturer: v })} />
              <Typeahead label="Model" required value={f.model} options={models} onChange={(v) => set({ model: v })} />
              {dups.length > 0 && (
                <p className="banner" role="status">
                  ⚠ {profileTitle(dups[0])} already exists ({dups.map((d) => d.name).join(', ')}). Use that profile from the palette, or add a variant with a different name.
                </p>
              )}
              <label className="field">Asset type *
                <select aria-label="Asset type" value={f.assetType} onChange={(e) => set({ assetType: e.target.value })}>
                  <option value="">Choose…</option>
                  {ASSET_TYPES.map((a) => <option key={a} value={a}>{ASSET_LABEL[a]}</option>)}
                </select>
              </label>
              {PROFILE_API.orientation && f.assetType === 'switch' && (
                <label className="field">Orientation *
                  <select aria-label="Orientation" value={f.orientation} onChange={(e) => {
                    const o = e.target.value as ProfileForm['orientation']
                    // Auto name "{model} (Power Front)" unless the user has typed their own.
                    const auto = !f.name.trim() || (f.orientation !== '' && f.name === orientationName(f.model, f.orientation))
                    set({ orientation: o, ...(auto && o ? { name: orientationName(f.model, o) } : {}) })
                  }}>
                    <option value="">Choose…</option>
                    {ORIENTATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
              )}
            </fieldset>
            <fieldset><legend>Profile</legend>
              <label className="field">Name *<input aria-label="Profile name" value={f.name} onChange={(e) => set({ name: e.target.value })} /></label>
              <label className="field">U height *
                <input type="number" min={0} max={100} step={1} {...RU_INPUT} aria-label="U height" value={f.uHeight} onChange={(e) => set({ uHeight: e.target.value })} />
              </label>
              <label className="field">Mounting *
                <select aria-label="Mounting" value={f.mounting} onChange={(e) => set({ mounting: e.target.value })}>
                  {MOUNTINGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                {!PROFILE_API.lifecycle && <span className="hint">Not saved yet: the API has no mounting field.</span>}
              </label>
              <div className="field" role="radiogroup" aria-label="Depth">Depth *
                <label><input type="radio" name="ap-depth" checked={f.fullDepth} onChange={() => set({ fullDepth: true })} /> Full</label>
                <label><input type="radio" name="ap-depth" checked={!f.fullDepth} onChange={() => set({ fullDepth: false })} /> Half</label>
              </div>
              <div className="ap-dims">{num('widthMm', 'Width (mm)')}{num('heightMm', 'Height (mm)')}{num('depthMm', 'Depth (mm)')}</div>
              {warn && <p className="hint" role="note">⚠ {warn}</p>}
              <label className="field">Power type *
                <select aria-label="Power type" value={f.powerType} onChange={(e) => set({ powerType: e.target.value })}>
                  <option value="">—</option><option value="AC">AC</option><option value="DC">DC</option><option value="AC_DC">AC and DC</option>
                </select>
              </label>
              <ImageDropzone label="Front image *" uHeight={Number(f.uHeight)} file={f.frontImage} onChange={(fi) => set({ frontImage: fi })} />
              <ImageDropzone label="Rear image *" uHeight={Number(f.uHeight)} file={f.rearImage} onChange={(fi) => set({ rearImage: fi })} />
              <p className="hint">Both photos are required to publish: straight on, cropped to the chassis, even light, at least 1024 px wide.</p>
              {savedId != null && <p className="hint">Images are uploaded when the draft is saved; to replace one later, use the profile's ⋯ menu.</p>}
            </fieldset>
            {error && <p className="field-error" role="alert">{error}</p>}
            {saved && <p role="status">{saved}</p>}
            <div className="actions">
              <button type="button" onClick={onClose}>Cancel</button>
              <button type="submit" disabled={!canSaveDraft(f) || busy || savedId != null}>{savedId != null ? 'Draft saved' : 'Save draft'}</button>
              <button type="button" className="primary" disabled={!PROFILE_API.publish || !canPublish || !canSaveDraft(f) || busy || published}
                title={canPublish ? undefined : 'Publishing needs the Admin role'} onClick={() => void publish()}>
                {published ? 'Published' : busy ? 'Working…' : 'Publish'}
              </button>
            </div>
            {!canPublish && <p className="hint">Publishing needs the Admin role; save a draft and ask an admin.</p>}
          </form>
          <aside className="ap-side">
            <h3>Preview (rack front)</h3>
            <div className="ap-preview" style={{ height: u * PREVIEW_RU, position: 'relative' }} data-testid="profile-preview">
              <DeviceFront device={preview} lod={2} ru={PREVIEW_RU} passThrough={false} conflict={false} />
            </div>
            {!f.frontImage && <p className="hint">◇ Needs image</p>}
            <h3>Publish checklist</h3>
            <ul className="checklist" aria-label="Publish checklist">
              {items.map((i) => <li key={i.key} className={i.ok ? 'ok' : 'bad'}><span aria-hidden="true">{i.ok ? '✓' : '✗'}</span> {i.label}<span className="visually-hidden">{i.ok ? ': done' : ': missing'}</span></li>)}
            </ul>
            <p className="hint">{missing === 0 ? 'Ready to publish' : `${missing} item${missing === 1 ? '' : 's'} missing`}. The server's check decides when Publish is available.</p>
          </aside>
        </div>
      </div>
    </div>
  )
}
