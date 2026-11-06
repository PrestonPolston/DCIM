// THE single data source for the row front view: useRowFront(hallId, rowId).
//
// INTERIM (2026-10-24): the spec's GET /rows/{id}/front (row-front.md §9
// Backend 1) and profile front images (docs/db/PROFILE_IMAGES.md) are not in
// the API yet. Until they are, this hook composes GET /halls/{id}/layout plus
// one GET /racks/{id}/elevation per cabinet (parallel, shared TanStack Query
// cache with the cabinet page) and maps them into the spec's RowFrontData.
// asset_type is left undefined; images are read via
// frontImageOf() when the API sends them, otherwise the fallback fronts render. To switch to the real endpoint, replace the
// body of useRowFront with one useQuery on rowsApi.front(rowId); nothing else
// in the app reads these endpoints for the row view.
import { useQueries } from '@tanstack/react-query'
import { DEFAULT_SETTINGS } from '../lib/hallLayout'
import { rowFacing, settingsFromHint, type RowFrontData, type RowFrontDevice, type RowFrontRack } from '../lib/rowFront'
import { racksApi } from './client'
import { frontImageOf, rearImageOf } from './profiles'
import { rackKeys, useHallLayout } from './racks'
import type { ElevationApiDevice, HallLayout, RackElevationResponse } from './types'

export const rowFrontKeys = { all: ['row-front'] as const }

function readLocalSettings(hallId: number) {
  try {
    const raw = localStorage.getItem(`dcim.hall.${hallId}.layout`)
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : null
  } catch {
    return null
  }
}

const MOUNTINGS = ['rack_19in', 'rack_23in', 'shelf', 'zero_u', 'other'] as const

/** is_full_depth / mounting / depth_mm on elevation items (from the profile, HEAD). Absent on older servers. */
function depthOf(d: ElevationApiDevice): Pick<RowFrontDevice, 'is_full_depth' | 'mounting' | 'depth_mm'> {
  const o = d as unknown as Record<string, unknown>
  const dt = d.device_type as { is_full_depth?: boolean } | null | undefined
  return {
    is_full_depth: typeof o.is_full_depth === 'boolean' ? o.is_full_depth : (dt?.is_full_depth ?? true),
    mounting: MOUNTINGS.includes(o.mounting as never) ? (o.mounting as RowFrontDevice['mounting']) : null,
    depth_mm: typeof o.depth_mm === 'number' ? o.depth_mm : null,
  }
}

/** manufacturer/model/weight_kg (HEAD) and orientation (pending Backend) on items; tolerant when absent. */
function modelOf(d: ElevationApiDevice): Pick<RowFrontDevice, 'manufacturer' | 'model' | 'weight_kg' | 'orientation'> {
  const o = d as unknown as Record<string, unknown>
  const str = (v: unknown) => (typeof v === 'string' && v ? v : null)
  return {
    manufacturer: str(o.manufacturer) ?? d.device_type?.manufacturer ?? null,
    model: str(o.model) ?? d.device_type?.name ?? null,
    weight_kg: typeof o.weight_kg === 'number' ? o.weight_kg : null,
    orientation: o.orientation === 'power_front' || o.orientation === 'port_front' ? o.orientation : null,
  }
}

/** One elevation item → the row-front/cabinet device shape (images, asset type, flags). */
export function toRowFrontDevice(d: ElevationApiDevice): RowFrontDevice {
  return {
    id: d.id, host_name: d.host_name, status: d.status, serial_number: d.serial_number,
    position_u: d.position_u, top_u: d.top_u, face: d.face, device_type: d.device_type ?? null,
    profile_id: d.profile_id ?? null,
    effective_asset_type: d.effective_asset_type ?? (d.device_type as { asset_type?: string | null } | null)?.asset_type ?? null,
    serial_unavailable: d.serial_unavailable ?? null, serial_note: d.serial_note ?? null,
    needs_review: d.needs_review ?? null, needs_review_reason: d.needs_review_reason ?? null,
    effective_front_image: frontImageOf(d),
    effective_rear_image: rearImageOf(d),
    ...depthOf(d),
    ...modelOf(d),
  }
}

export function mapRowFront(layout: HallLayout, rowId: number, elevations: (RackElevationResponse | undefined)[]): RowFrontData | null {
  const row = layout.rows.find((r) => r.id === rowId)
  if (!row) return null
  const hall = { id: layout.id, name: layout.name, aisle_axis: layout.aisle_axis ?? null, odd_side: layout.odd_side ?? null }
  const settings = settingsFromHint(hall, readLocalSettings(layout.id), DEFAULT_SETTINGS)
  const racks: RowFrontRack[] = row.racks.map((r, i) => ({
    id: r.id, name: r.name, u_height: r.u_height, pos_x: r.pos_x, pos_y: r.pos_y,
    effective_orientation: r.effective_orientation ?? null, u_used: r.u_used, u_free: r.u_free,
    devices: (elevations[i]?.devices ?? []).map(toRowFrontDevice),
  }))
  return {
    row: { id: row.id, name: row.name, hall_id: layout.id, orientation: row.orientation, effective_facing: rowFacing(layout.rows, row.id, settings) },
    hall,
    racks,
  }
}

export function useRowFront(hallId: number, rowId: number) {
  const layout = useHallLayout(hallId)
  const row = layout.data?.rows.find((r) => r.id === rowId)
  const els = useQueries({
    queries: (row?.racks ?? []).map((r) => ({ queryKey: rackKeys.elevation(r.id), queryFn: () => racksApi.elevation(r.id) })),
  })
  const elData = els.map((q) => q.data)
  const pending = layout.isPending || els.some((q) => q.isPending)
  const error = layout.error ?? els.find((q) => q.error)?.error ?? null
  // Cheap (≤ ~400 devices); recomputed per render so cache updates show at once.
  const data = layout.data && !pending ? mapRowFront(layout.data, rowId, elData) : undefined
  return { data, isPending: pending, error, notFound: !!layout.data && !row }
}
