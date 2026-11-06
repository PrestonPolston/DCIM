import { useState, type FormEvent } from 'react'
import { rackPath, useLookups } from '../api/racks'
import type { Device, DeviceCreate, Rack } from '../api/types'
import { initialValues, toBody, validate, type FormValues } from './device-form/model'
import Section from './device-form/Section'
import ConfirmDialog from './ConfirmDialog'
import ProfileSummary from './profiles/ProfileSummary'
import { profileTitle, type UiProfile } from '../api/profiles'
import { ApiError } from '../api/client'
import { SECTIONS } from './device-form/sections'

interface Props {
  /** When set, the form is in edit mode. */
  device?: Device
  /** Prefill (overrides device), e.g. from an RU drop. */
  initial?: Partial<DeviceCreate>
  title?: string
  /** Place-device mode: location is fixed and shown as text. */
  locationText?: string
  submitLabel?: string
  onSubmit: (values: DeviceCreate) => Promise<void>
  onCancel: () => void
  /** Placing from a profile: shown read-only (ProfileSummary) instead of the Model/Profile pickers. */
  profile?: UiProfile | null
  onChangeProfile?: () => void
}

export default function DeviceForm({ device, initial, title, locationText, submitLabel, onSubmit, onCancel, profile, onChangeProfile }: Props) {
  const editing = device !== undefined
  const { racks, rows, halls, sites, deviceTypes } = useLookups()
  const [values, setValues] = useState<FormValues>(() => initialValues({ ...device, ...initial }))
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notUsable, setNotUsable] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmDecom, setConfirmDecom] = useState(false)

  const all = validate(values)
  const errors = submitted ? all : Object.fromEntries(Object.entries(all).filter(([k]) => touched.has(k)))
  const lookups = {
    deviceTypes,
    racks,
    rackLabel: (r: Rack) => [rackPath(r, rows, halls, sites), r.name].filter(Boolean).join(' › '),
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setSubmitted(true)
    if (Object.keys(all).length) {
      e.currentTarget.querySelector<HTMLElement>(all.host_name ? '#df-host' : '#df-rack')?.focus()
      return
    }
    if (editing && device.status !== 'decom' && values.status === 'decom') {
      setConfirmDecom(true)
      return
    }
    await submit(toBody(values))
  }

  async function submit(body: DeviceCreate) {
    setError(null)
    setNotUsable(false)
    setSaving(true)
    try {
      await onSubmit(body)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setNotUsable(err instanceof ApiError && err.code === 'profile_not_usable')
    } finally {
      setSaving(false)
    }
  }

  const props = {
    values,
    set: (patch: Partial<FormValues>) => setValues((v) => ({ ...v, ...patch })),
    errors,
    touch: (f: keyof FormValues) => setTouched((t) => new Set(t).add(f)),
    lookups,
    locationText,
    profileLocked: !!profile,
    initialProfileId: device?.profile_id ?? null,
  }

  return (
    <form className="card form" onSubmit={handleSubmit} noValidate aria-label={title ?? (editing ? 'Edit device' : 'New device')}>
      <div className="form-header">
        <button type="button" className="ghost icon" aria-label="Close" onClick={onCancel} disabled={saving}>✕</button>
        <h2>{title ?? (editing ? `Edit ${device.host_name}` : 'New device')}</h2>
      </div>
      {profile && <ProfileSummary profile={profile} onChange={onChangeProfile} />}
      {SECTIONS.filter((s) => s.Fields).map(({ id, title: t, Fields }) => (
        <Section key={id} title={t}>
          {Fields && <Fields {...props} />}
        </Section>
      ))}
      {error && <p className="error" role="alert">{error}{notUsable && <> <a href="/profiles?review=1">Upload a rear image for {profile ? profileTitle(profile) : 'this profile'} first →</a></>}</p>}
      <div className="actions">
        <button type="submit" className="primary" disabled={saving}>{saving ? 'Saving…' : (submitLabel ?? 'Save')}</button>
        <button type="button" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
      {confirmDecom && editing && (
        <ConfirmDialog title={`Decom ${device.host_name}?`} confirmLabel="Decom" danger busy={saving}
          onCancel={() => setConfirmDecom(false)}
          onConfirm={() => { setConfirmDecom(false); void submit({ ...toBody(values), rack_id: null, position_u: null }) }}>
          <p>{device.rack_id ? 'It will be removed from its cabinet (unracked). ' : ''}Its connections are kept and shown as Decom.</p>
        </ConfirmDialog>
      )}
    </form>
  )
}
