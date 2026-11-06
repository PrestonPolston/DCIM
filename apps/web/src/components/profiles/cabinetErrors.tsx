// Cabinet-profile error states (admin-setup.md §6) for Backend's built codes (docs/API.md "Cabinet profiles",
// feat/cabinet-profiles 43bbb1e) → form/banner content.
import { Link } from 'react-router'
import { cabinetError } from '../../api/cabinetProfiles'
import { PUBLISH_LABELS } from '../../api/cabinetProfiles.mock'
import { friendlyMessage } from '../../api/errors'
import { LENGTH_LABELS } from '../../lib/cabinetForm'
import { formatApiDate } from '../../lib/apiDate'
import type { ErrorMapper } from './CabinetProfileForm'

const FIELD_LABELS: Record<string, string> = { ...PUBLISH_LABELS, ...LENGTH_LABELS, weight_capacity_kg: 'Weight capacity', u_height: 'U height', color_hex: 'Colour', notes: 'Notes', front_door: 'Front door', rear_door: 'Rear door' }
const labelOf = (k: string) => FIELD_LABELS[k] ?? k
const DIMENSION_COPY: Record<string, string> = {
  usable_width_mm: "Can't be more than the outer width.", usable_depth_mm: "Can't be more than the outer depth.",
  rail_depth_min_mm: "Can't be more than the rail depth max.", rail_depth_max_mm: "Can't be more than the outer depth.",
}
/** Plain copy for one FastAPI validation item (lengths only need to be > 0; no upper caps). */
function validationCopy(it: { type?: string; msg?: string; loc?: unknown[] }): string {
  const k = String(it.loc?.at(-1) ?? '')
  if (it.type === 'greater_than') return 'Must be greater than 0.'
  if ((it.type === 'less_than_equal' || it.type === 'greater_than_equal') && k === 'u_height') return 'U height must be a whole number from 1 to 100.'
  if (it.type === 'literal_error') return `Not an allowed value. ${it.msg ?? ''}`.trim()
  if (it.type === 'string_too_short') return 'Required.'
  return it.msg ?? 'Invalid value.'
}
export const NETWORK_MSG = "Can't reach the server. Your changes are still here; try again."

/** `action` picks the 403 copy: creating vs changing. */
export function cabinetErrorView(e: unknown, action: 'create' | 'change' = 'change', ctx: { title?: string; status?: string } = {}): ReturnType<ErrorMapper> {
  const { status, code, message, detail } = cabinetError(e)
  if (status === 0 && /fetch|network/i.test(message)) return { message: NETWORK_MSG }
  if (status === 403) return { message: action === 'create' ? 'Only admins can create cabinet profiles.' : 'Only admins can change cabinet profiles.' }
  switch (code) {
    case 'cabinet_profile_name_taken': {
      const id = detail.existing_id as number | undefined
      const name = ctx.title ?? 'A profile with this manufacturer, model and variant'
      return {
        message: `${name} already exists.`, field: { name: 'Use another variant name.' },
        node: ({ focusVariant }) => <>{id != null && <Link className="button" to={`/profiles/cabinet/${id}`}>Open it</Link>}<button type="button" onClick={focusVariant}>Use another variant name</button></>,
      }
    }
    case 'cabinet_profile_incomplete': {
      const missing = Array.isArray(detail.missing) ? (detail.missing as string[]) : []
      const list = missing.map(labelOf).join(', ')
      if (ctx.status === 'published') return { message: `A published profile must stay complete. Fill in: ${list}.`, missing }
      return { message: `Not ready to publish. ${missing.length} item${missing.length === 1 ? '' : 's'} missing: ${missing.map(labelOf).join(', ')}.`, missing }
    }
    case 'invalid_dimension': {
      const fields = Array.isArray(detail.fields) ? (detail.fields as string[]) : []
      const field: Record<string, string> = {}
      for (const k of fields) field[k] = DIMENSION_COPY[k] ?? 'Must fit inside the outer size.'
      return { message: fields.length ? `Check ${fields.map(labelOf).join(', ')}: usable sizes and rail depths must fit inside the outer size.` : 'Usable sizes and rail depths must fit inside the outer size.', field }
    }
    case 'version_conflict': {
      const at = typeof detail.current_updated_at === 'string' ? formatApiDate(detail.current_updated_at) : null
      const by = typeof detail.updated_by === 'string' && detail.updated_by ? detail.updated_by : 'someone else'
      return { message: `Changed by ${by} since you opened it${at ? ` (saved ${at})` : ''}. Reload to see the latest; your edits here are not saved.`, node: ({ reload }) => <button type="button" onClick={reload}>Reload</button> }
    }
    case 'cabinet_profile_retired':
      return { message: 'This profile is retired, so it is read-only. Un-retire it or clone it.' }
    case 'invalid_status_transition': {
      const from = typeof detail.status === 'string' ? detail.status : null, to = typeof detail.to === 'string' ? detail.to : null
      return { message: from && to ? `A ${from} profile can't become ${to}. Reload to see its current state.` : 'That change isn’t allowed in this state. Reload and try again.' }
    }
    case 'cabinet_profile_in_use': {
      const by = typeof detail.superseded_by === 'number' ? detail.superseded_by : null
      if (detail.reason === 'superseded') {
        return { message: `Can't delete: in use. A newer version${by != null ? ` (profile #${by})` : ''} supersedes it. Retire it instead, or delete the newer one first.`,
          node: () => (by != null ? <Link className="button" to={`/profiles/cabinet/${by}`}>Open newer version</Link> : null) }
      }
      return { message: "Can't delete: in use. Retire it instead." }
    }
  }
  if (status === 422) {
    const errs = detail.errors
    if (errs && typeof errs === 'object') return { message: 'Check the highlighted fields.', field: errs as Record<string, string> }
    // FastAPI validation array: [{type, loc: ['body', 'width_mm'], msg}]
    const raw = (e as { detail?: { detail?: unknown } }).detail?.detail
    if (Array.isArray(raw)) {
      const field: Record<string, string> = {}
      const items = raw as { type?: string; loc?: unknown[]; msg?: string }[]
      if (items.some((it) => it.type === 'invalid_unit')) return { message: 'Units must be mm or in.' }
      for (const it of items) { const k = it.loc?.at(-1); if (typeof k === 'string') field[k] = validationCopy(it) }
      return { message: `Check the highlighted fields: ${Object.keys(field).map(labelOf).join(', ')}.`, field }
    }
  }
  if (code) { const f = friendlyMessage({ code }, status); if (f) return { message: f } }
  if (status >= 500) return { message: `Server error (${status}). Your changes are still here; try again.` }
  return { message }
}
