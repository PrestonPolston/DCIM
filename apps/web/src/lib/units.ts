// mm ↔ in for profile dimensions (admin-setup.md §3; ADMIN_INPUT_PLAN rev 3 §4c).
// Storage is always mm. Cabinet dimensions are stored as whole mm (half-up); device dimensions
// keep 0.1 mm. Inches are shown to 2 dp. The UI converts client-side and always sends mm.
export const MM_PER_IN = 25.4
export type LengthUnit = 'mm' | 'in'
/** 'cabinet' = whole mm; 'device' = 0.1 mm. */
export type MmPrecision = 'cabinet' | 'device'

/** Half-up rounding to `step` that is immune to binary noise (e.g. 1.005 → 1.01). */
export function roundHalfUp(x: number, step: number): number {
  const q = Number((x / step).toFixed(9))
  const r = Math.sign(q) * Math.floor(Math.abs(q) + 0.5)
  return Number((r * step).toFixed(step < 1 ? String(step).split('.')[1]?.length ?? 1 : 0))
}
export const roundMm = (mm: number, p: MmPrecision = 'cabinet') => roundHalfUp(mm, p === 'cabinet' ? 1 : 0.1)
export const inToMm = (inches: number, p: MmPrecision = 'cabinet') => roundMm(inches * MM_PER_IN, p)
export const mmToIn = (mm: number) => roundHalfUp(mm / MM_PER_IN, 0.01)

/** Display a number without trailing zeros: 600 → "600", 23.6 → "23.6". */
export const trimNum = (n: number) => String(Number(n.toFixed(2)))
export const fmtMm = (mm: number, dp = 0) => `${mm.toFixed(dp)} mm`
export const fmtIn = (mm: number) => `${mmToIn(mm).toFixed(2)} in`
/** Text for an input in `unit`, given the stored mm. */
export const mmToInput = (mm: number | null | undefined, unit: LengthUnit) => (mm == null ? '' : unit === 'mm' ? trimNum(mm) : trimNum(mmToIn(mm)))

export const NUMBER_MSG = 'Enter a number (e.g. 600 or 23.62).'
export const POSITIVE_MSG = 'Must be greater than 0.'
export const U_HEIGHT_MSG = 'U height must be a whole number from 1 to 100.'

export type ParsedLength = { ok: true; empty: false; mm: number } | { ok: true; empty: true; mm: null } | { ok: false; empty: false; mm: null; error: string }

/**
 * Parse a length typed in `unit`. Accepts "600", " 23.62 ", "23,62", and a matching suffix
 * ("600 mm", "23.62in", '23.62"'). Empty is ok (required-ness is the checklist's job).
 * A value that rounds to 0 mm fails "> 0".
 */
export function parseLength(text: string, unit: LengthUnit, p: MmPrecision = 'cabinet'): ParsedLength {
  let t = text.trim().toLowerCase().replace(',', '.')
  if (!t) return { ok: true, empty: true, mm: null }
  t = unit === 'mm' ? t.replace(/\s*mm$/, '') : t.replace(/\s*(in|inch|inches|")$/, '')
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return { ok: false, empty: false, mm: null, error: NUMBER_MSG }
  const n = Number(t)
  if (!(n > 0)) return { ok: false, empty: false, mm: null, error: POSITIVE_MSG }
  const mm = unit === 'mm' ? roundMm(n, p) : inToMm(n, p)
  if (!(mm > 0)) return { ok: false, empty: false, mm: null, error: POSITIVE_MSG }
  return { ok: true, empty: false, mm }
}

/** Live converted value under a field: "600 mm = 23.62 in" / "23.62 in = 600 mm". */
export function convertedText(text: string, unit: LengthUnit, p: MmPrecision = 'cabinet'): string | null {
  const r = parseLength(text, unit, p)
  if (!r.ok || r.empty) return null
  const dp = p === 'cabinet' ? 0 : 1
  return unit === 'mm' ? `${fmtMm(r.mm, dp)} = ${fmtIn(r.mm)}` : `${trimNum(Number(text.trim().replace(',', '.').replace(/[^\d.+-]/g, '')))} in = ${fmtMm(r.mm, dp)}`
}

export function parseUHeight(text: string): { ok: true; value: number | null } | { ok: false; error: string } {
  const t = text.trim()
  if (!t) return { ok: true, value: null }
  if (!/^\d+$/.test(t)) return { ok: false, error: U_HEIGHT_MSG }
  const n = Number(t)
  return n >= 1 && n <= 100 ? { ok: true, value: n } : { ok: false, error: U_HEIGHT_MSG }
}

/** Optional positive number (kg etc.), no unit conversion. */
export function parsePositive(text: string): { ok: true; value: number | null } | { ok: false; error: string } {
  const t = text.trim().replace(',', '.')
  if (!t) return { ok: true, value: null }
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return { ok: false, error: NUMBER_MSG }
  return Number(t) > 0 ? { ok: true, value: Number(t) } : { ok: false, error: POSITIVE_MSG }
}
