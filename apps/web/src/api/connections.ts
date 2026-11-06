// Connections v1 (docs/API.md "Connections (v1)"): GET /connections, GET /connections/export.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { listPage, send } from './client'

export const CABLE_TYPES = ['RJ45', 'LC', 'DAC'] as const

export interface ConnectionEnd {
  device_id: number; host_name: string; status: string
  rack_id: number | null; cabinet: string | null; hall_id: number | null; hall: string | null; row: string | null
  position_u: number | null; face: 'front' | 'rear' | null
  port_id: number; port_name: string; slot: string | null
}
export interface Cable { id: number; cable_type: string | null; label: string | null; color: string | null; length_m: string | number | null }
export interface Connection {
  id: number; a: ConnectionEnd; b: ConnectionEnd; cable: Cable | null
  derived_status: string; notes: string | null; created_at: string
}
export interface ConnectionFilters {
  hall_id?: number; rack_id?: number; device_id?: number
  cable_type?: string; derived_status?: string; cross_cabinet?: boolean; q?: string
}

function qs(p: object) {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== '' && v !== false) s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const connectionsApi = {
  list: (p: ConnectionFilters & { limit?: number; offset?: number }) => listPage<Connection>('/connections', p),
  exportCsv: async (p: ConnectionFilters) => (await send(`/connections/export${qs(p)}`, { headers: { Accept: 'text/csv' } })).text(),
}

export function useConnections(p: ConnectionFilters & { limit?: number; offset?: number }, enabled = true) {
  return useQuery({ queryKey: ['connections', p], queryFn: () => connectionsApi.list(p), placeholderData: keepPreviousData, enabled })
}

/** "Demo Hall / R01 / R01-C01 / RU2 F", or "— Unplaced". */
export function endLocation(e: ConnectionEnd): string {
  if (!e.rack_id) return '— Unplaced'
  return [e.hall, e.row, e.cabinet, e.position_u != null ? `RU${e.position_u} ${e.face === 'rear' ? 'R' : 'F'}` : null].filter(Boolean).join(' / ')
}
