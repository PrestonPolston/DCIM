// Friendly copy for structured API error codes ({detail: {code, message, missing?}}),
// checked against apps/api (devices/service.py, lifecycle.py, connections) at a289079/72fee98.
// One place to add codes; ApiError.message uses this when a code is known.
const COPY: Record<string, string> = {
  profile_required: 'Choose a profile (manufacturer, model and variant) before placing this device in a cabinet.',
  profile_not_published: "This profile isn't published yet (or was retired). Pick a published profile.",
  profile_not_usable: "This profile needs review before it can be used for new devices. Existing devices on it are unaffected.",
  profile_type_mismatch: "The profile doesn't belong to the chosen model. Pick a profile of that model.",
  profile_in_use: 'Devices use this profile, so it can’t be changed or deleted. Create a new version or retire it instead.',
  device_has_connections: "This device still has connections. Delete its connections first.",
  port_in_use: 'That port is already connected. Pick a free port.',
  self_connection: "A port can't be connected to itself.",
  cable_label_conflict: 'Another cable already has this label. Use a different label.',
  image_too_large: 'The image is too large (max 2 MiB and 4096 × 4096 px).',
  svg_not_allowed: "SVG isn't supported. Export a PNG.",
  // P1-10 (f2dab41): a concurrent writer took the slot between our check and commit.
  ru_slot_taken: 'Someone just placed a device in those U slots. Refresh the cabinet and pick a free position.',
  floor_position_taken: 'Another cabinet was just placed on that floor position. Refresh and pick a free cell.',
  // Cabinet profiles (docs/API.md "Cabinet profiles", feat/cabinet-profiles 43bbb1e).
  cabinet_profile_incomplete: 'Not ready to publish.',
  invalid_status_transition: "That change isn't allowed in this state. Reload and try again.",
  invalid_dimension: 'Usable sizes and rail depths must fit inside the outer size.',
  cabinet_profile_retired: 'This profile is retired, so it is read-only. Un-retire it or clone it.',
  cabinet_profile_in_use: "Can't delete: in use. Retire it instead.",
  cabinet_profile_name_taken: 'A profile with this manufacturer, model and variant already exists.',
  version_conflict: 'Changed by someone else since you opened it. Reload to see the latest.',
  // Job intake v1 (Backend slice 1 uses job_exists; duplicate_dcreq is treated as the same hard stop).
  dcreq_format: 'Enter a DCREQ like DCREQ0001234 (DCREQ000 + 4 digits).',
  duplicate_dcreq: 'That DCREQ is already a job. Attaching more work to that job isn’t available yet.',
  job_exists: 'That DCREQ is already a job. Attaching more work to that job isn’t available yet.',
  import_forbidden_columns: 'This file has forbidden columns. Remove those columns and upload again. Secrets are never stored.',
  unknown_columns: 'This file has unknown columns. Remove them and upload again.',
  duplicate_columns: 'This file has duplicate columns. Remove the extras and upload again.',
  missing_columns: 'This file is missing required columns. Add them and upload again.',
  import_empty: 'This file has no data rows.',
  job_not_empty: 'This job already has committed work, so it can’t be deleted. Close it instead.',
  job_has_open_items: 'This job still has unresolved items. You can close it anyway.',
  job_already_closed: 'This job is already closed.',
  job_already_open: 'This job is already open.',
  job_not_found: 'Job not found.',
  import_kind_not_available: "Cable matrix import isn't available yet. Skip it; the item will stay in the fill-later queue.",
  job_closed: 'This job is closed. Reopen it to import files.',
  no_review_imports: 'There are no imports in review on this job.',
  import_not_in_review: "This import isn't in review.",
  note_required: 'A note is required to dismiss an item.',
  open_item_closed: 'This item is already completed.',
  open_item_state: "That action isn't valid for this item's current status.",
  invalid_text: "This note has characters that aren't allowed.",
  formula_prefix: "This note can't start with =, +, - or @.",
}

const TEXT_FIELD_LABELS: Record<string, string> = {
  note: 'note',
  dcreq: 'DCREQ',
  name: 'name',
  description: 'description',
}

/** Friendly copy for coded job-intake text 422s, with the field name when we have it. */
export function textRejectionCopy(code: 'invalid_text' | 'formula_prefix', field?: string | null): string {
  const label = (field && TEXT_FIELD_LABELS[field]) || 'text'
  if (code === 'formula_prefix') return `This ${label} can't start with =, +, - or @.`
  return `This ${label} has characters that aren't allowed.`
}

/** True when a trimmed value starts with a spreadsheet-formula character. */
export function startsWithFormulaPrefix(value: string): boolean {
  return /^[=+\-@]/.test(value.trim())
}

/**
 * Simulate the API's job-intake text rules (docs/API.md at 2282a2a).
 * Notes may contain \n and tab and may start with = + - @; other controls are invalid_text.
 * name, description and dcreq are single-line and keep the formula guard.
 * The client must not rewrite the user's input; this is only for the mock and live-route fixture.
 */
export function jobTextViolation(
  field: string,
  value: string | null | undefined,
  kind: 'note' | 'single_line' = field === 'note' ? 'note' : 'single_line',
): { code: 'invalid_text' | 'formula_prefix'; message: string; field: string } | null {
  if (value == null) return null
  const stored = kind === 'note' ? value.replace(/\r\n/g, '\n') : value
  const trimmed = stored.trim()
  if (kind === 'single_line') {
    if (!trimmed) return null
    if (startsWithFormulaPrefix(trimmed)) {
      return { code: 'formula_prefix', message: textRejectionCopy('formula_prefix', field), field }
    }
    if ([...trimmed].some((ch) => {
      const c = ch.charCodeAt(0)
      return c < 32 || c === 127
    })) {
      return { code: 'invalid_text', message: textRejectionCopy('invalid_text', field), field }
    }
    return null
  }
  if (!stored) return null
  if ([...stored].some((ch) => {
    const c = ch.charCodeAt(0)
    return (c < 32 && ch !== '\n' && ch !== '\t') || c === 127
  })) {
    return { code: 'invalid_text', message: textRejectionCopy('invalid_text', field), field }
  }
  return null
}

/** 409 on editing a flagged device: the code is its needs_review_reason (lifecycle.py _check_flagged_edit). */
const FLAGGED: Record<string, string> = {
  placed_without_profile: 'This device was placed without a profile. Choose a profile, unplace it, or decommission it before other edits.',
  profile_not_published: "This device's profile isn't published. Choose a published profile, unplace it, or decommission it before other edits.",
}

export interface ExistingJobRef { id: number; dcreq: string; name: string; status: string; is_job?: boolean; deleted?: boolean }
export interface ErrorDetail {
  code?: string
  message?: string
  missing?: string[]
  profile_id?: number
  issues?: string[]
  reason?: string
  existing?: ExistingJobRef
  headers?: string[]
  columns?: string[]
  unresolved_count?: number
  field?: string
}

export function errorDetail(detail: unknown): ErrorDetail | null {
  const d = (detail as { detail?: unknown } | undefined)?.detail
  return d && typeof d === 'object' && !Array.isArray(d) ? (d as ErrorDetail) : null
}

export function friendlyMessage(d: ErrorDetail, status?: number): string | null {
  if (!d.code) return null
  if (d.code === 'invalid_text' || d.code === 'formula_prefix') {
    return textRejectionCopy(d.code, d.field)
  }
  const base = (status === 409 && FLAGGED[d.code]) || COPY[d.code]
  if (!base) return null
  if (d.code === 'profile_not_usable') {
    const issues = d.issues ?? (d.reason ? [d.reason] : [])
    if (issues.includes('rear_image_missing')) return 'Upload a rear image for this profile first. Existing devices on it are unaffected.'
    if (issues.includes('orientation_missing')) return 'Set the orientation (Power front / Port front) for this profile first.'
  }
  if ((d.code === 'import_forbidden_columns' || d.code === 'unknown_columns') && (d.headers?.length || d.columns?.length)) {
    const names = (d.headers ?? d.columns ?? []).join(', ')
    return d.code === 'import_forbidden_columns'
      ? `This file has forbidden columns: ${names}. Remove those columns and upload again. Secrets are never stored.`
      : `This file has unknown columns: ${names}. Remove them and upload again.`
  }
  if ((d.code === 'duplicate_dcreq' || d.code === 'job_exists') && d.existing) {
    const e = d.existing
    return `${e.dcreq} is already a job (${e.name}, ${e.status}). Attaching more work to that job isn’t available yet.`
  }
  if (d.code === 'job_has_open_items' && typeof d.unresolved_count === 'number') {
    const n = d.unresolved_count
    return `This job still has ${n} unresolved item${n === 1 ? '' : 's'}. You can close it anyway.`
  }
  return d.missing?.length ? `${base} Missing: ${d.missing.join(', ')}.` : base
}

/** Turn a pydantic/FastAPI validation message into readable copy. */
export function stripPydanticText(msg: string, field?: string | null): string {
  let s = msg.trim()
  let inferred = field ?? null
  s = s.replace(/^(?:body\.)?([A-Za-z0-9_]+):\s*/i, (_, loc: string) => {
    inferred = inferred ?? loc.toLowerCase()
    return loc.toLowerCase() === 'note' ? '' : `${loc}: `
  })
  s = s.replace(/^Value error,\s*/i, '')
  s = s.replace(/^assertion failed,\s*/i, '')
  s = s.trim()
  if (!inferred) {
    const m = s.match(/\b(note|dcreq|name|description)\b/i)
    if (m) inferred = m[1].toLowerCase()
  }
  if (/must not contain control characters/i.test(s)) return textRejectionCopy('invalid_text', inferred)
  if (/must not start with|= \+ - @|spreadsheet formula/i.test(s)) return textRejectionCopy('formula_prefix', inferred)
  return s
}

export function formatValidationErrors(details: unknown[]): string {
  return details.map((entry) => {
    const e = entry as { loc?: unknown[]; msg?: string; message?: string }
    const loc = (e.loc ?? []).filter((x) => x !== 'body' && x !== 'query' && x !== 'path').join('.')
    const stripped = stripPydanticText(String(e.msg ?? e.message ?? ''))
    if (loc && loc !== 'note' && !stripped.toLowerCase().startsWith(`${loc.toLowerCase()}:`)) {
      return `${loc}: ${stripped}`
    }
    return stripped
  }).filter(Boolean).join('; ')
}

/** Inline copy for a coded or leftover-pydantic text 422 on a specific field. */
export function textFieldError(e: unknown, field?: string | null): string | null {
  const err = e as { code?: string | null; status?: number; detail?: unknown; message?: string }
  const d = errorDetail(err.detail)
  const code = d?.code ?? err.code
  const errField = d?.field ?? field
  if (code === 'invalid_text' || code === 'formula_prefix') {
    if (field && errField && errField !== field) return null
    return friendlyMessage({ ...(d ?? {}), code, field: errField ?? field ?? undefined }, err.status)
      ?? textRejectionCopy(code, errField ?? field)
  }
  const msg = typeof err.message === 'string' ? err.message : ''
  if (!msg) return null
  const stripped = stripPydanticText(msg, field)
  if (/control characters|spreadsheet formula|aren't allowed|can't start with =/i.test(msg) ||
      /aren't allowed|can't start with =/.test(stripped)) {
    if (field && !new RegExp(field, 'i').test(msg) && !new RegExp(field, 'i').test(stripped) && !/note/i.test(field)) {
      // still accept generic control/formula phrasing when the field was not named
    }
    return stripped
  }
  return null
}

/** Inline / page copy for a note-field 422 (coded or leftover pydantic text). */
export function noteFieldError(e: unknown): string | null {
  return textFieldError(e, 'note')
}
