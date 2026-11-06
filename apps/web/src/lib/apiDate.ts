// API timestamps: some come without an offset ("2026-11-04T00:49:51.06", stored UTC), others with
// "+00:00". Treat offset-less ones as UTC so they show in the viewer's time zone correctly.
export function parseApiDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso)
  const d = new Date(hasZone || !iso.includes('T') ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}
export const formatApiDate = (iso: string | null | undefined) => parseApiDate(iso)?.toLocaleString() ?? null
