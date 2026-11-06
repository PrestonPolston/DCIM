// In-memory fake of the DCIM API (docs/API.md v0.1) for component tests.
import { vi } from 'vitest'
import type { Device, DeviceType, Hall, Rack, Row, Site } from '../api/types'

/** Profiles: 7 and 9 published (type defaults), 8 a draft variant. */
export const PROFILES = [
  { id: 7, device_type_id: 1, name: 'R650 default', is_default: true, u_height: 2, is_full_depth: true, status: 'published' },
  { id: 8, device_type_id: 1, name: 'R650 GPU', is_default: false, u_height: 2, is_full_depth: true, status: 'draft' },
  { id: 9, device_type_id: 2, name: 'Default', is_default: true, u_height: 1, is_full_depth: false, status: 'published' },
]

export interface Db {
  sites: Site[]; halls: Hall[]; rows: Row[]; racks: Rack[]; 'device-types': DeviceType[]; devices: Device[]
}

export function seedDb(): Db {
  return {
    sites: [{ id: 1, name: 'DAL1' }],
    halls: [{ id: 1, site_id: 1, name: 'Hall 2' }],
    rows: [{ id: 1, hall_id: 1, name: 'Row 3' }],
    // Mixed heights in one row: R12 is 53U (new API default), R13 is 42U.
    racks: [{ id: 12, row_id: 1, name: 'R12', u_height: 53 }, { id: 13, row_id: 1, name: 'R13', u_height: 42 }],
    'device-types': [
      { id: 1, manufacturer: 'Dell', name: 'R650', u_height: 2, is_full_depth: true },
      { id: 2, manufacturer: 'Arista', name: '7050X', u_height: 1, is_full_depth: false },
    ],
    devices: [
      { id: 1, host_name: 'web-01', status: 'active', serial_number: 'SN-A1', rack_id: 12, position_u: 2, face: 'front', device_type_id: 1 },
      { id: 2, host_name: 'db-01', status: 'decom', serial_number: null, rack_id: null, position_u: null, face: 'front', device_type_id: 2 },
    ],
  }
}

export type Handler = (method: string, path: string, body: unknown) => Response | undefined

export interface AuthState { signedIn: boolean; role: string; csrf: string; mustChange?: boolean }
export const auth: AuthState = { signedIn: true, role: 'admin', csrf: 'csrf-1' }
export function resetAuth(patch: Partial<AuthState> = {}) {
  Object.assign(auth, { signedIn: true, role: 'admin', csrf: 'csrf-1', mustChange: false }, patch)
}
const me = () => ({ id: 1, email: 'pat@example.com', display_name: 'Pat', role: auth.role, must_change_password: !!auth.mustChange, csrf_token: auth.csrf })

export function installMockApi(db: Db, override?: Handler) {
  const calls: { method: string; url: string; body: unknown; csrf: string | null; credentials?: RequestCredentials }[] = []
  const fn = vi.fn(async (input: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const url = new URL(input, 'http://x')
    const path = url.pathname.replace(/^\/api/, '')
    const isBlob = typeof Blob !== 'undefined' && init?.body instanceof Blob
    const raw = init?.body && !isBlob ? String(init.body) : undefined
    let body: unknown = isBlob ? init!.body : undefined
    if (!isBlob) try { body = raw ? JSON.parse(raw) : undefined } catch { body = raw }
    const headers = new Headers(init?.headers)
    calls.push({ method, url: path + url.search, body, csrf: headers.get('X-CSRF-Token'), credentials: init?.credentials })
    const json = (b: unknown, status = 200, headers: Record<string, string> = {}) =>
      new Response(b === undefined ? null : JSON.stringify(b), { status, headers })
    const o = override?.(method, path, body)
    if (o) return o
    if (path === '/auth/login') {
      const b = body as { email: string; password: string }
      if (b.password !== 'right') return json({ detail: 'Invalid email or password' }, 401)
      auth.signedIn = true
      return json(me())
    }
    if (!auth.signedIn) return json({ detail: 'Not authenticated' }, 401)
    if (method !== 'GET' && headers.get('X-CSRF-Token') !== auth.csrf) return json({ detail: 'CSRF token missing or invalid' }, 403)
    if (path === '/auth/me') return json(me())
    if (path === '/auth/logout') { auth.signedIn = false; return json(undefined, 204) }
    if (method !== 'GET' && auth.role === 'read-only') return json({ detail: 'Requires role: admin or technician' }, 403)
    const typeOf = (d: Device) => db['device-types'].find((t) => t.id === d.device_type_id)
    const uOf = (d: Device) => typeOf(d)?.u_height ?? 1
    const usage = (rackId: number) => {
      const placed = db.devices.filter((d) => d.rack_id === rackId && d.position_u != null)
      return { device_count: db.devices.filter((d) => d.rack_id === rackId).length, u_used: placed.reduce((n, d) => n + uOf(d), 0) }
    }
    let m = path.match(/^\/halls\/(\d+)\/layout$/)
    if (m) {
      const hall = db.halls.find((h) => h.id === Number(m![1]))!
      return json({
        ...hall,
        rows: db.rows.filter((r) => r.hall_id === hall.id).map((r) => ({
          pos_x: null, pos_y: null, orientation: null, ...r,
          racks: db.racks.filter((k) => k.row_id === r.id).map((k) => {
            const u = usage(k.id)
            return { pos_x: null, pos_y: null, orientation: null, ...k, ...u, u_free: k.u_height - u.u_used }
          }),
        })),
      })
    }
    if (path === '/devices/export') {
      const head = 'id,host_name,status,serial_number,rack_id'
      const lines = db.devices.map((d) => [d.id, d.host_name, d.status, d.serial_number ?? '', d.rack_id ?? ''].join(','))
      return new Response([head, ...lines].join('\r\n') + '\r\n', { status: 200, headers: { 'Content-Type': 'text/csv' } })
    }
    if (path === '/devices/import' && method === 'POST') {
      const lines = String(body ?? '').trim().split(/\r?\n/)
      const head = lines[0].split(',')
      const errors: { row: number; errors: string[] }[] = []
      lines.slice(1).forEach((l, i) => {
        const r = Object.fromEntries(l.split(',').map((v, k) => [head[k], v]))
        if ((r.rack_id || r.position_u) && !r.profile_id && !db['device-types'].some((t) => t.manufacturer === r.manufacturer && t.name === r.model))
          errors.push({ row: i + 2, errors: [`Unknown device type '${r.manufacturer} ${r.model}'`] })
      })
      return json({ dry_run: url.searchParams.get('dry_run') !== 'false', total_rows: lines.length - 1, created: 0, errors, errors_truncated: false, warnings: [] })
    }
    if (path === '/profiles' && method === 'GET') {
      let items = PROFILES.map((p) => {
        const t = db['device-types'].find((x) => x.id === p.device_type_id)!
        return { manufacturer: t.manufacturer, model: t.name, asset_type: null, effective_asset_type: null, front_image: null,
          device_count: db.devices.filter((d) => d.profile_id === p.id || (p.is_default && d.device_type_id === t.id && d.profile_id == null)).length, ...p }
      })
      const st = url.searchParams.get('status')
      const q = url.searchParams.get('q')?.toLowerCase()
      const at = url.searchParams.get('asset_type')
      if (st) items = items.filter((p) => p.status === st)
      if (q) items = items.filter((p) => [p.manufacturer, p.model, p.name].some((x) => x.toLowerCase().includes(q)))
      if (at) items = items.filter((p) => (p.effective_asset_type ?? p.asset_type) === at)
      const lim = Number(url.searchParams.get('limit') ?? 50)
      return json(items.slice(0, lim), 200, { 'X-Total-Count': String(items.length) })
    }
    const im = path.match(/^\/device-types\/(\d+)\/profiles\/(\d+)\/images\/(front|rear)$/)
    if (im && method === 'PUT') return json({ face: im[3], url: `/profile-images/${im[2]}/${im[3]}`, thumb_url: `/profile-images/${im[2]}/${im[3]}?variant=thumb` })
    const pp = path.match(/^\/device-types\/(\d+)\/profiles\/(\d+)$/)
    if (pp && method === 'PATCH') return json({ ...PROFILES.find((x) => x.id === Number(pp[2])), ...(body as object) })
    const cl = path.match(/^\/profiles\/(\d+)\/clone$/)
    if (cl && method === 'POST') return json({ ...PROFILES.find((x) => x.id === Number(cl[1])), id: 500, status: 'draft', is_default: false, ...(body as object) }, 201)
    const pm = path.match(/^\/device-types\/(\d+)\/profiles$/)
    if (pm) {
      const t = Number(pm[1])
      if (method === 'POST') {
        const created = { id: 100 + Math.floor(Math.random() * 1000), device_type_id: t, is_default: false, u_height: 1, ...(body as object) }
        return json(created, 201)
      }
      return json(PROFILES.filter((p) => p.device_type_id === t))
    }
    m = path.match(/^\/racks\/(\d+)\/elevation$/)
    if (m) {
      const rack = db.racks.find((k) => k.id === Number(m![1]))!
      const u = usage(rack.id)
      const devices = db.devices
        .filter((d) => d.rack_id === rack.id && d.position_u != null)
        .sort((a, b) => a.position_u! - b.position_u!)
        .map((d) => ({ id: d.id, host_name: d.host_name, status: d.status, serial_number: d.serial_number ?? null,
          position_u: d.position_u, top_u: d.position_u! + uOf(d) - 1, face: d.face ?? 'front', device_type: typeOf(d) ?? null,
          ...(d.needs_review != null ? { needs_review: d.needs_review, needs_review_reason: d.needs_review_reason ?? null } : {}) }))
      return json({ ...rack, u_used: u.u_used, u_free: rack.u_height - u.u_used, devices })
    }
    const [, res, idStr] = path.split('/') as [string, keyof Db, string?]
    const table = db[res] as { id: number }[] | undefined
    if (!table) return json({ detail: 'Not Found' }, 404)
    if (method === 'GET' && !idStr) {
      let items = table as unknown as Record<string, unknown>[]
      for (const [k, v] of url.searchParams) {
        if (k === 'limit' || k === 'offset') continue
        if (k === 'unplaced') items = items.filter((i) => (v === 'true') === (i.rack_id == null))
        else if (k === 'q') items = items.filter((i) => [i.host_name, i.serial_number, i.name].some((x) => String(x ?? '').toLowerCase().includes(v.toLowerCase())))
        else items = items.filter((i) => String(i[k]) === v)
      }
      const off = Number(url.searchParams.get('offset') ?? 0)
      const lim = Number(url.searchParams.get('limit') ?? 50)
      return json(items.slice(off, off + lim), 200, { 'X-Total-Count': String(items.length) })
    }
    const id = Number(idStr)
    const found = table.find((i) => i.id === id)
    if (method === 'GET') return found ? json(found) : json({ detail: 'Not found' }, 404)
    if ((method === 'POST' || method === 'PATCH') && res === 'devices') {
      const b = { ...(method === 'PATCH' ? found : {}), ...(body as object) } as Device
      if (b.rack_id != null && b.device_type_id == null && b.profile_id == null)
        return json({ detail: { code: 'profile_required', message: 'Placing a device requires a profile' } }, 422)
      if (b.rack_id != null && b.position_u == null)
        return json({ detail: 'Placing a device in a cabinet requires position_u' }, 422)
    }
    if (method === 'POST') {
      const item = { id: Math.max(0, ...table.map((i) => i.id)) + 1, status: 'active', face: 'front', ...(body as object) }
      table.push(item)
      return json(item, 201)
    }
    if (method === 'PATCH') {
      const { recommission: _r, ...rest } = (body ?? {}) as Record<string, unknown>
      void _r
      Object.assign(found!, rest)
      // Server lifecycle: Decom auto-unracks.
      if (res === 'devices' && rest.status === 'decom') Object.assign(found!, { rack_id: null, position_u: null })
      return json(found)
    }
    if (method === 'DELETE') {
      ;(db[res] as { id: number }[]) = table.filter((i) => i.id !== id)
      return json(undefined, 204)
    }
    return json({}, 400)
  })
  vi.stubGlobal('fetch', fn)
  return calls
}
