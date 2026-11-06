import { errorDetail, friendlyMessage } from './errors'
import type {
  Device, DeviceCreate, DeviceProfile, DeviceListParams, DeviceType, DeviceUpdate, Hall, HallLayout, ListParams, Page, Rack, RackElevationResponse, Row, Site,
} from './types'

export const API_BASE_URL = (import.meta.env.VITE_API_URL ?? '/api').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  /** Structured error code, e.g. 'profile_required'. */
  readonly code: string | null

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = errorDetail(detail)?.code ?? null
  }
}

// CSRF token from POST /auth/login or GET /auth/me. Kept in memory only.
let csrfToken: string | null = null
export function setCsrfToken(token: string | null) {
  csrfToken = token
}
export function getCsrfToken() {
  return csrfToken
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include', // session cookie (same-origin via the Vite proxy)
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(UNSAFE.has(method) && csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
      ...init.headers,
    },
  })
  if (!res.ok) {
    let detail: unknown
    try {
      detail = await res.json()
    } catch {
      detail = undefined
    }
    const d = (detail as { detail?: unknown } | undefined)?.detail
    const msg =
      typeof d === 'string'
        ? d
        : Array.isArray(d)
          ? d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join('.')}: ${e.msg}`).join('; ')
          : errorDetail(detail) && friendlyMessage(errorDetail(detail)!, res.status)
            ? friendlyMessage(errorDetail(detail)!, res.status)!
          : d && typeof d === 'object' && typeof (d as { message?: unknown }).message === 'string'
            ? (d as { message: string }).message // e.g. {code: 'hostname_conflict', message}
            : `${res.status} ${res.statusText}`.trim()
    throw new ApiError(res.status, res.status === 403 ? `Not allowed: ${msg}` : msg, detail)
  }
  return res
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function qs(params: object): string {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

export async function listPage<T>(path: string, params: object = {}): Promise<Page<T>> {
  const res = await send(`${path}${qs(params)}`)
  const items = (await res.json()) as T[]
  const header = res.headers.get('X-Total-Count')
  return { items, total: header !== null ? Number(header) : items.length }
}

function resource<T, C = Partial<T>, P extends ListParams = ListParams>(path: string) {
  return {
    list: (params: P = {} as P) => listPage<T>(path, params),
    get: (id: number) => request<T>(`${path}/${id}`),
    create: (body: C) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
    update: (id: number, body: Partial<C>) => request<T>(`${path}/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    remove: (id: number) => request<void>(`${path}/${id}`, { method: 'DELETE' }),
  }
}

export const devicesApi = {
  ...resource<Device, DeviceCreate, DeviceListParams>('/devices'),
  /** GET /devices/export (text/csv) with the same filters as the list. */
  exportCsv: async (params: Omit<DeviceListParams, 'limit' | 'offset'> = {}) => (await send(`/devices/export${qs(params)}`, { headers: { Accept: 'text/csv' } })).text(),
}
export const sitesApi = resource<Site, Partial<Site>, ListParams>('/sites')
export const hallsApi = {
  ...resource<Hall, Partial<Hall>, ListParams & { site_id?: number }>('/halls'),
  layout: (id: number) => request<HallLayout>(`/halls/${id}/layout`),
}
export const rowsApi = resource<Row, Partial<Row>, ListParams & { hall_id?: number }>('/rows')
export const racksApi = {
  ...resource<Rack, Partial<Rack>, ListParams & { row_id?: number; hall_id?: number }>('/racks'),
  elevation: (id: number) => request<RackElevationResponse>(`/racks/${id}/elevation`),
}
export const deviceTypesApi = {
  ...resource<DeviceType, Partial<DeviceType>, ListParams & { manufacturer?: string }>('/device-types'),
  profiles: (typeId: number) => request<DeviceProfile[]>(`/device-types/${typeId}/profiles`),
}

export type { DeviceUpdate }
