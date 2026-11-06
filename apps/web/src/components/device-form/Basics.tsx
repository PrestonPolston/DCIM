import { STATUSES, statusClass, statusIcon, statusLabel } from '../../lib/status'
import type { SectionProps } from './model'
import { typeLabel, useDeviceProfiles } from '../../api/racks'
import { issueLabel, usabilityOf } from '../../api/profiles'
import { ID_INPUT } from '../../lib/inputs'

export default function Basics({ values, set, errors, touch, lookups, profileLocked, initialProfileId }: SectionProps) {
  const profiles = useDeviceProfiles(values.device_type_id ? Number(values.device_type_id) : null).data ?? []
  const statuses: string[] = (STATUSES as readonly string[]).includes(values.status) ? [...STATUSES] : [...STATUSES, values.status]
  return (
    <>
      <label className="field">
        Hostname *
        <input id="df-host" className="mono" aria-label="Hostname" {...ID_INPUT} enterKeyHint="next" value={values.host_name}
          onChange={(e) => set({ host_name: e.target.value })} onBlur={() => touch('host_name')}
          aria-invalid={errors.host_name ? true : undefined} />
        {errors.host_name ? <span className="field-error">{errors.host_name}</span> : <span className="hint">Must be unique within its cabinet.</span>}
      </label>
      <fieldset className="field plain">
        <legend>Status</legend>
        <div className="segmented" role="radiogroup" aria-label="Status">
          {statuses.map((s) => (
            <button key={s} type="button" role="radio" aria-checked={values.status === s} aria-pressed={values.status === s}
              className={statusClass(s)} onClick={() => set({ status: s })}>
              <span aria-hidden="true">{statusIcon(s)}</span> {statusLabel(s)}
            </button>
          ))}
        </div>
      </fieldset>
      <label className="field">
        Serial Number
        <input className="mono" aria-label="Serial Number" {...ID_INPUT} enterKeyHint="next" value={values.serial_unavailable ? '' : values.serial_number}
          disabled={values.serial_unavailable} onChange={(e) => set({ serial_number: e.target.value })} />
        <span className="hint">Vendor serial or asset tag. Optional; must be unique when set.</span>
      </label>
      <label className="check-row">
        <input type="checkbox" checked={values.serial_unavailable} onChange={(e) => set({ serial_unavailable: e.target.checked })} />
        Serial not accessible (installed / blocked)
      </label>
      {values.serial_unavailable && (
        <label className="field">
          Serial note
          <input aria-label="Serial note" maxLength={128} value={values.serial_note} onChange={(e) => set({ serial_note: e.target.value })} />
          <span className="hint">Optional. Not saved yet: the API has no serial_note field.</span>
        </label>
      )}
      {!profileLocked && (<>
      <label className="field">
        Model{values.rack_id ? ' *' : ''}
        <select aria-label="Model" value={values.device_type_id} onChange={(e) => set({ device_type_id: e.target.value, profile_id: '' })}>
          <option value="">{values.rack_id ? 'Choose a model' : '— None (unplaced) —'}</option>
          {lookups.deviceTypes.map((t) => <option key={t.id} value={t.id}>{typeLabel(t)}</option>)}
        </select>
        {errors.device_type_id && <span className="field-error" role="alert">{errors.device_type_id}</span>}
      </label>
      {profiles.length > 0 && (
        <label className="field">
          Profile
          <select aria-label="Profile" value={values.profile_id} onChange={(e) => set({ profile_id: e.target.value })}>
            <option value="">— type default —</option>
            {profiles.map((p) => {
              // Existing assignment stays selectable; new use of an unusable profile is blocked (422 profile_not_usable).
              const u = usabilityOf(p as unknown as Record<string, unknown>)
              // Only the published-but-unusable (Needs review) case is disabled here; drafts keep the server's 422.
              const blocked = (p as { status?: string }).status === 'published' && !u.usable && String(p.id) !== String(initialProfileId ?? '')
              return <option key={p.id} value={p.id} disabled={blocked}>{p.name}{p.is_default ? ' (default)' : ''}{blocked ? ` — ${u.issues.map(issueLabel).join(', ')}` : ''}</option>
            })}
          </select>
        </label>
      )}
      </>)}
    </>
  )
}
