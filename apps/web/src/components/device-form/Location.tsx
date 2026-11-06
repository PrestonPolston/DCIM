import type { SectionProps } from './model'
import { RU_INPUT } from '../../lib/inputs'

export default function Location({ values, set, errors, lookups, locationText }: SectionProps) {
  if (locationText !== undefined)
    return <p className="field">Location <span className="mono">{locationText}</span></p>
  return (
    <>
      <label className="field">
        Cabinet
        <select id="df-rack" aria-label="Cabinet" value={values.rack_id} onChange={(e) => set({ rack_id: e.target.value })}>
          <option value="">— no cabinet —</option>
          {lookups.racks.map((r) => <option key={r.id} value={r.id}>{lookups.rackLabel(r)}</option>)}
        </select>
      </label>
      <label className="field">
        Position (lowest RU)
        <input type="number" min={1} {...RU_INPUT} aria-label="Position (RU)" value={values.position_u}
          disabled={!values.rack_id} onChange={(e) => set({ position_u: e.target.value })} />
        {errors.position_u && <span className="field-error">{errors.position_u}</span>}
      </label>
      <fieldset className="field plain">
        <legend>Face</legend>
        <div className="segmented" role="group" aria-label="Face">
          {(['front', 'rear'] as const).map((f) => (
            <button key={f} type="button" aria-pressed={values.face === f} onClick={() => set({ face: f })}>
              {f === 'front' ? 'Front' : 'Rear'}
            </button>
          ))}
        </div>
      </fieldset>
      {errors.placement && <p className="field-error">{errors.placement}</p>}
      <label className="field">
        Legacy location label
        <input aria-label="Legacy location label" value={values.rack} onChange={(e) => set({ rack: e.target.value })} />
        <span className="hint">Optional free text.</span>
      </label>
    </>
  )
}
