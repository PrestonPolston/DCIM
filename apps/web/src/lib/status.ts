// THE single source of device-status vocabulary. Swap this list (and icons)
// when the API's status enum changes; nothing else hardcodes status values.
// Unknown values (e.g. legacy rows) render neutral with a "?" icon.
export const STATUSES = ['install', 'active', 'decom'] as const
export type DeviceStatus = (typeof STATUSES)[number]
/** UI default for new devices (sent explicitly; the API's own default is still 'active'). */
export const DEFAULT_STATUS: DeviceStatus = 'install'
/** Status counted as an alert in rack summaries (if present in the vocabulary). */
export const ALERT_STATUS: string | null = null

const ICONS: Record<DeviceStatus, string> = { install: '◐', active: '●', decom: '⊘' }
const LABELS: Record<DeviceStatus, string> = { install: 'Install', active: 'Active', decom: 'Decom' }

export function isKnownStatus(s: string): s is DeviceStatus {
  return (STATUSES as readonly string[]).includes(s)
}

export function statusLabel(s: string): string {
  return isKnownStatus(s) ? LABELS[s] : s ? s[0].toUpperCase() + s.slice(1) : s
}

export function statusIcon(s: string): string {
  return isKnownStatus(s) ? ICONS[s] : '?'
}

/** CSS class for badges/blocks; unknown statuses get the neutral palette. */
export function statusClass(s: string): string {
  return isKnownStatus(s) ? `status-${s}` : 'status-unknown'
}

/**
 * Lifecycle transitions mirrored from the API (apps/api lifecycle.TRANSITIONS):
 * install → active | decom, active → decom, decom → (install | active with recommission).
 */
export function statusTransition(from: string, to: string): { ok: boolean; recommission?: boolean; reason?: string } {
  if (from === to) return { ok: false }
  if (from === 'install') return { ok: to === 'active' || to === 'decom', reason: 'Not allowed from Install' }
  if (from === 'active') return to === 'decom' ? { ok: true } : { ok: false, reason: 'An Active device can only go to Decom' }
  if (from === 'decom') return { ok: to === 'install' || to === 'active', recommission: true }
  return { ok: isKnownStatus(to) }
}
