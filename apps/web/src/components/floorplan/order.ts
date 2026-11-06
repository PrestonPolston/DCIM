import type { HallLayoutRack, HallLayoutRow } from '../../api/types'

const byPos = <T extends { name: string }>(key: (t: T) => number | null) => (a: T, b: T) => {
  const ka = key(a)
  const kb = key(b)
  if (ka != null && kb != null && ka !== kb) return ka - kb
  if (ka != null && kb == null) return -1
  if (ka == null && kb != null) return 1
  return a.name.localeCompare(b.name, undefined, { numeric: true })
}

/** Rows top-to-bottom by pos_y, falling back to name. */
export const sortRows = (rows: HallLayoutRow[]) => [...rows].sort(byPos((r) => r.pos_y))
/** Cabinets left-to-right by pos_x, falling back to name. */
export const sortCabinets = (racks: HallLayoutRack[]) => [...racks].sort(byPos((r) => r.pos_x))
