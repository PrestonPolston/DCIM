// Location / cabinet (API: rack) / device-type hooks (docs/API.md).
import { useQuery } from '@tanstack/react-query'
import { drawAsPlaceholder } from '../lib/needsProfile'
import type { ElevationDevice } from '../components/rack/layout'
import { deviceTypesApi, hallsApi, racksApi, rowsApi, sitesApi } from './client'
import type { DeviceType, Hall, ListParams, Rack, RackElevationResponse, Row, Site } from './types'

const MAX = 500 // API list limit ceiling

export const rackKeys = {
  all: ['racks'] as const,
  list: (p: ListParams) => [...rackKeys.all, 'list', p] as const,
  elevation: (id: number) => ['elevation', id] as const,
}
export const hallKeys = { all: ['halls'] as const, layout: (id: number) => ['hall-layout', id] as const }

export function useHalls() {
  return useQuery({ queryKey: [...hallKeys.all, 'all'], queryFn: () => hallsApi.list({ limit: MAX }) })
}

export function useHallLayout(id: number | undefined, enabled = true) {
  return useQuery({ queryKey: hallKeys.layout(id ?? 0), queryFn: () => hallsApi.layout(id!), enabled: enabled && !!id })
}

export function useDeviceTypes() {
  return useQuery({ queryKey: ['device-types', 'all'], queryFn: () => deviceTypesApi.list({ limit: MAX }) })
}

/** Lookup tables for pickers and name display (first 500 of each). */
export function useLookups() {
  const sites = useQuery({ queryKey: ['sites', 'all'], queryFn: () => sitesApi.list({ limit: MAX }) })
  const halls = useHalls()
  const rows = useQuery({ queryKey: ['rows', 'all'], queryFn: () => rowsApi.list({ limit: MAX }) })
  const racks = useQuery({ queryKey: [...rackKeys.all, 'all'], queryFn: () => racksApi.list({ limit: MAX }) })
  const types = useDeviceTypes()
  return {
    sites: sites.data?.items ?? [],
    halls: halls.data?.items ?? [],
    rows: rows.data?.items ?? [],
    racks: racks.data?.items ?? [],
    deviceTypes: types.data?.items ?? [],
  }
}

export function rackPath(rack: Rack | undefined, rows: Row[], halls: Hall[], sites: Site[]): string {
  if (!rack) return ''
  const row = rows.find((r) => r.id === rack.row_id)
  const hall = halls.find((h) => h.id === row?.hall_id)
  const site = sites.find((s) => s.id === hall?.site_id)
  return [site?.name, hall?.name, row?.name].filter(Boolean).join(' › ')
}

export function typeLabel(t: DeviceType | undefined): string {
  return t ? `${t.manufacturer} ${t.name} · ${t.u_height}U` : ''
}

export function toElevationDevices(e: RackElevationResponse | undefined): ElevationDevice[] {
  return (e?.devices ?? []).map((d) => {
    const ph = drawAsPlaceholder(d) // no profile geometry: 1U, both faces
    return {
      id: d.id, host_name: d.host_name, status: d.status, position_u: d.position_u, face: d.face,
      serial_number: d.serial_number,
      height_u: ph ? 1 : d.device_type!.u_height, is_full_depth: ph ? true : d.device_type!.is_full_depth,
      model: d.device_type?.name, needs_review: d.needs_review === true, needs_review_reason: d.needs_review_reason ?? null,
    }
  })
}

/** Single source for a cabinet's elevation: GET /racks/{id}/elevation. */
export function useRackElevation(id: number, enabled = true) {
  return useQuery({ queryKey: rackKeys.elevation(id), queryFn: () => racksApi.elevation(id), enabled })
}

export function useDeviceProfiles(typeId: number | null) {
  return useQuery({
    queryKey: ['device-types', typeId, 'profiles'],
    queryFn: () => deviceTypesApi.profiles(typeId!),
    enabled: typeId != null,
  })
}
