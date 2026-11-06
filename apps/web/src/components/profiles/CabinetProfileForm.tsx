// Cabinet profile create/edit form (admin-setup.md §3, deck v4). Lengths are typed in mm or in
// (one toggle), stored as whole mm; each length shows its converted value live.
import { useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { DOOR_TYPES, RACK_UNIT_WIDTHS, RAIL_TYPES, useCabinetActions, useCabinetProfiles, type CabinetProfile } from '../../api/cabinetProfiles'
import {
  cabinetChecklist, canSaveDraft, emptyCabinetForm, formFromProfile, LENGTH_LABELS, lengthMm, missingSentence, switchUnit, toBody, validateCabinet,
  type CabinetForm, type FieldErrors, type LengthField,
} from '../../lib/cabinetForm'
import { convertedText, type LengthUnit } from '../../lib/units'
import ImageDropzone from './ImageDropzone'

export type FormError = { message: string; field?: Partial<Record<string, string>> }
/** Turns a thrown error into what the form shows. */
export type ErrorMapper = (e: unknown, ctx?: { title?: string }) => FormError & { node?: (ctx: { focusVariant: () => void; reload: () => void }) => ReactNode; missing?: string[] }
const genericMapper: ErrorMapper = (e) => ({ message: e instanceof Error ? e.message : 'Something went wrong.' })

export default function CabinetProfileForm({ profile, onClose, onSaved, mapError = genericMapper, onReload }: {
  /** Edit an existing profile; omitted = create. */
  profile?: CabinetProfile
  onClose: () => void
  onSaved?: (p: CabinetProfile) => void
  mapError?: ErrorMapper
  onReload?: () => void
}) {
  const initial = useMemo(() => (profile ? formFromProfile(profile) : emptyCabinetForm()), [profile])
  const [f, setF] = useState<CabinetForm>(initial)
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [submitted, setSubmitted] = useState(false)
  const [saved, setSaved] = useState<CabinetProfile | null>(profile ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ReturnType<ErrorMapper> | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [serverMissing, setServerMissing] = useState<string[] | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [dirty, setDirty] = useState(false)
  const actions = useCabinetActions()
  const { data: existing = [] } = useCabinetProfiles({ status: 'all' })
  const variantRef = useRef<HTMLInputElement>(null)
  const uid = useId()
  const locked = false // the API keeps published profiles editable (it only refuses making them incomplete)
  const retired = saved?.status === 'retired'

  const set = (patch: Partial<CabinetForm>) => { setF((c) => ({ ...c, ...patch })); setDirty(true); setServerMissing(null) }
  const setLen = (k: LengthField, v: string) => { setF((c) => ({ ...c, len: { ...c.len, [k]: v } })); setDirty(true); setServerMissing(null) }
  const touch = (k: string) => setTouched((t) => (t.has(k) ? t : new Set(t).add(k)))
  const local = validateCabinet(f)
  const serverField = error?.field ?? {}
  const errOf = (k: keyof FieldErrors | string): string | undefined => ((touched.has(k) || submitted) ? (local as Record<string, string | undefined>)[k] : undefined) ?? serverField[k]
  const items = cabinetChecklist(f, serverMissing)
  const dup = existing.find((p) => p.id !== saved?.id && [p.manufacturer, p.model, p.name].join('\u0000').toLowerCase() === [f.manufacturer.trim(), f.model.trim(), f.name.trim()].join('\u0000').toLowerCase())

  function close() { if (dirty && !confirmDiscard) setConfirmDiscard(true); else onClose() }

  async function persist(): Promise<CabinetProfile> {
    const body = toBody(f)
    let p: CabinetProfile
    if (!saved) p = await actions.create(body)
    else if (!dirty) p = saved
    else p = await actions.update(saved.id, { ...body, expected_updated_at: saved.updated_at })
    if (f.frontImage) p = await actions.uploadImage(p.id, 'front', f.frontImage)
    if (f.rearImage) p = await actions.uploadImage(p.id, 'rear', f.rearImage)
    setSaved(p); setDirty(false); setF((c) => ({ ...c, frontImage: null, rearImage: null }))
    onSaved?.(p)
    return p
  }
  async function run(kind: 'save' | 'publish') {
    setSubmitted(true); setError(null); setStatus(null)
    if (Object.keys(local).length) { setError({ message: 'Check the highlighted fields.' }); return }
    setBusy(true)
    try {
      const p = await persist()
      if (kind === 'publish') {
        const pub = await actions.publish(p.id)
        setSaved(pub); onSaved?.(pub); setServerMissing([])
        setStatus(`Published ${f.manufacturer.trim()} ${f.model.trim()} · ${pub.name}.`)
      } else setStatus(`Saved draft ${f.manufacturer.trim()} ${f.model.trim()} · ${p.name}.`)
    } catch (e) {
      const m = mapError(e, { title: `${f.manufacturer.trim()} ${f.model.trim()} · ${f.name.trim() || 'Standard'}` })
      if (m.missing) setServerMissing(m.missing)
      setError(m)
    } finally { setBusy(false) }
  }

  const describe = (...ids: (string | false | null | undefined)[]) => ids.filter(Boolean).join(' ') || undefined
  const text = (k: 'manufacturer' | 'model' | 'name', label: string, extra?: { ref?: typeof variantRef; listId?: string }) => {
    const err = errOf(k), eid = `${uid}-${k}-err`
    return (
      <label className="field">{label} *
        <input ref={extra?.ref} aria-label={label} value={f[k]} disabled={locked || retired} aria-invalid={!!err} aria-describedby={describe(err && eid)}
          onBlur={() => touch(k)} onChange={(e) => set({ [k]: e.target.value } as Partial<CabinetForm>)} />
        <span id={eid} className="field-error" aria-live="polite">{err ?? ''}</span>
      </label>
    )
  }
  const length = (k: LengthField, required = false) => {
    const label = LENGTH_LABELS[k], err = errOf(k), eid = `${uid}-${k}-err`, cid = `${uid}-${k}-conv`
    const conv = err ? null : convertedText(f.len[k], f.unit)
    return (
      <label className="field">{label} ({f.unit}){required ? ' *' : ''}
        <input inputMode="decimal" aria-label={`${label} (${f.unit})`} value={f.len[k]} disabled={locked || retired} aria-invalid={!!err}
          aria-describedby={describe(err && eid, conv && cid)} onBlur={() => touch(k)} onChange={(e) => setLen(k, e.target.value)} />
        {err ? <span id={eid} className="field-error" aria-live="polite">{err}</span>
          : <span id={cid} className="hint cp-conv" aria-live="polite">{conv ?? ''}</span>}
      </label>
    )
  }
  const select = <T extends string,>(label: string, value: T | '', opts: [T, string][], onChange: (v: T | '') => void, blank = '—') => (
    <label className="field">{label}
      <select aria-label={label} value={value} disabled={locked || retired} onChange={(e) => onChange(e.target.value as T | '')}>
        <option value="">{blank}</option>
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  )
  const outer = (['width_mm', 'depth_mm', 'height_mm'] as const).map((k) => lengthMm(f, k))
  const uErr = errOf('u_height'), uEid = `${uid}-u-err`
  const kgErr = errOf('weight_capacity_kg'), colErr = errOf('color_hex')

  return (
    <div className="ap-grid">
      <form className="form" noValidate aria-label="Cabinet profile" onSubmit={(e) => { e.preventDefault(); if (canSaveDraft(f)) void run('save') }}>
        {saved?.status === 'published' && <p className="banner" role="note">This profile is published: changes apply right away, and every required field must stay filled.</p>}
        {retired && <p className="banner" role="note">Retired profiles are read-only. Un-retire it to change it.</p>}
        <fieldset><legend>Identity</legend>
          {text('manufacturer', 'Manufacturer')}
          {text('model', 'Model')}
          {text('name', 'Variant name', { ref: variantRef })}
          {dup && !error && (
            <p className="banner" role="status">⚠ {dup.manufacturer} {dup.model} · {dup.name} already exists. Use another variant name.</p>
          )}
        </fieldset>
        <fieldset><legend>Size</legend>
          <label className="field">U height *
            <input inputMode="numeric" aria-label="U height" value={f.uHeight} disabled={locked || retired} aria-invalid={!!uErr} aria-describedby={describe(uErr && uEid)}
              onBlur={() => touch('u_height')} onChange={(e) => set({ uHeight: e.target.value })} />
            <span id={uEid} className="field-error" aria-live="polite">{uErr ?? ''}</span>
          </label>
          <div className="cp-unit">
            <span id={`${uid}-unit`}>Units</span>
            <div className="segmented" role="group" aria-labelledby={`${uid}-unit`}>
              {(['mm', 'in'] as LengthUnit[]).map((u) => (
                <button key={u} type="button" aria-pressed={f.unit === u} onClick={() => setF((c) => switchUnit(c, u))}>{u}</button>
              ))}
            </div>
            <span className="hint">Stored in mm (whole mm).</span>
          </div>
          <div className="ap-dims">{length('width_mm', true)}{length('depth_mm', true)}{length('height_mm', true)}</div>
          {f.unit === 'in' && outer.some((v) => v != null) && (
            <p className="hint mono" data-testid="stored-mm">= {outer.map((v) => (v == null ? '—' : v)).join(' × ')} mm (stored)</p>
          )}
          {select('Rack-unit width *', f.rackUnitWidth, RACK_UNIT_WIDTHS, (v) => set({ rackUnitWidth: v }), 'Choose…')}
        </fieldset>
        <fieldset><legend>Doors and rails</legend>
          <div className="ap-dims cp-two">
            {select('Front door', f.frontDoor, DOOR_TYPES, (v) => set({ frontDoor: v }))}
            {select('Rear door', f.rearDoor, DOOR_TYPES, (v) => set({ rearDoor: v }))}
          </div>
          {select('Rail holes', f.railType, RAIL_TYPES, (v) => set({ railType: v }))}
          <div className="ap-dims cp-two">{length('rail_depth_min_mm')}{length('rail_depth_max_mm')}</div>
        </fieldset>
        <fieldset><legend>Optional</legend>
          <div className="ap-dims cp-two">{length('usable_width_mm')}{length('usable_depth_mm')}</div>
          <div className="ap-dims cp-two">
            <label className="field">Weight capacity (kg)
              <input inputMode="decimal" aria-label="Weight capacity (kg)" value={f.maxLoadKg} disabled={locked || retired} aria-invalid={!!kgErr} aria-describedby={describe(kgErr && `${uid}-kg-err`)}
                onBlur={() => touch('weight_capacity_kg')} onChange={(e) => set({ maxLoadKg: e.target.value })} />
              <span id={`${uid}-kg-err`} className="field-error" aria-live="polite">{kgErr ?? ''}</span>
            </label>
            <label className="field">Colour
              <input aria-label="Colour" placeholder="#1F1F1F" value={f.colorHex} disabled={retired} aria-invalid={!!colErr} aria-describedby={describe(colErr && `${uid}-col-err`)}
                onBlur={() => touch('color_hex')} onChange={(e) => set({ colorHex: e.target.value })} />
              <span id={`${uid}-col-err`} className="field-error" aria-live="polite">{colErr ?? ''}</span>
            </label>
          </div>
          <label className="field">Notes<textarea aria-label="Notes" rows={2} value={f.notes} disabled={retired} onChange={(e) => set({ notes: e.target.value })} /></label>
          {!locked && !retired && <>
            <ImageDropzone label="Front image" optional file={f.frontImage} onChange={(fi) => set({ frontImage: fi })} />
            <ImageDropzone label="Rear image" optional file={f.rearImage} onChange={(fi) => set({ rearImage: fi })} />
            <p className="hint">Images are optional for cabinet profiles.</p>
          </>}
        </fieldset>
        <div role="alert" className="cp-error">{error && <p className="field-error">{error.message}{error.node?.({ focusVariant: () => { variantRef.current?.focus(); variantRef.current?.select(); setError(null) }, reload: () => onReload?.() })}</p>}</div>
        <p role="status" className="visually-hidden-when-empty">{status ?? ''}</p>
        {confirmDiscard ? (
          <div className="actions" role="group" aria-label="Discard changes?">
            <strong>Discard changes?</strong>
            <button type="button" onClick={() => setConfirmDiscard(false)}>Keep editing</button>
            <button type="button" className="danger" onClick={onClose}>Discard</button>
          </div>
        ) : (
          <div className="actions">
            <button type="button" onClick={close}>{saved && !dirty ? 'Close' : 'Cancel'}</button>
            {!retired && <button type="submit" disabled={!canSaveDraft(f) || busy || (!!saved && !dirty && !f.frontImage && !f.rearImage)}>{saved ? 'Save' : 'Save draft'}</button>}
            {saved?.status !== 'published' && !retired && (
              <button type="button" className="primary" disabled={!canSaveDraft(f) || busy} onClick={() => void run('publish')}>{busy ? 'Working…' : 'Publish'}</button>
            )}
          </div>
        )}
      </form>
      <aside className="ap-side">
        <h3>Publish checklist</h3>
        <ul className="checklist" aria-label="Publish checklist">
          {items.map((i) => <li key={i.key} className={i.ok ? 'ok' : 'bad'}><span aria-hidden="true">{i.ok ? '✓' : '✗'}</span> {i.label}<span className="visually-hidden">{i.ok ? ': done' : ': missing'}</span></li>)}
        </ul>
        <p className="hint" aria-live="polite">{missingSentence(items)}</p>
        <p className="hint">Images are optional. The server's check decides when Publish succeeds.</p>
      </aside>
    </div>
  )
}
