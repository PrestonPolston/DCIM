// Cabinet height helpers. Heights always come from the API's u_height
// (rack, hall layout racks[], elevation); DEFAULT_RACK_U is only a fallback
// when the field is missing (the API default is moving to 53).
export const DEFAULT_RACK_U = 53

/** Runs of at least this many empty RU may collapse into one row (rack-elevation.md). */
export const COLLAPSE_MIN_EMPTY_RU = 6

export function rackU(r: { u_height?: number | null } | null | undefined): number {
  const u = r?.u_height
  return typeof u === 'number' && Number.isFinite(u) && u >= 1 ? u : DEFAULT_RACK_U
}

/**
 * "R01-C14" → { prefix: "R01-", short: "C14" }: tiles sit next to their row label, so the
 * part after the last separator is what fits a 44–64px tile. Names without one stay whole.
 */
export function splitCabinetName(name: string): { prefix: string; short: string } {
  const m = /^(.*[-_.·/ ])([^-_.·/ ]+)$/.exec(name)
  return m ? { prefix: m[1], short: m[2] } : { prefix: '', short: name }
}
