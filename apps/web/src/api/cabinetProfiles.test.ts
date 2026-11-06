import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './client'
import { CABINET_PROFILE_API, PAGE, cabinetApi, cabinetError, resetCabinetMock, toCabinetProfile } from './cabinetProfiles'
import { createMockCabinetApi, readinessOf } from './cabinetProfiles.mock'

const codeOf = async (p: Promise<unknown>) => { try { await p } catch (e) { return cabinetError(e) } throw new Error('expected failure') }

describe('cabinet profile mock API (mirrors feat/cabinet-profiles contract)', () => {
  it('creates a draft with variant default "Standard" and reports readiness', async () => {
    const api = createMockCabinetApi({ rows: [] })
    const p = await api.create({ manufacturer: ' APC ', model: 'AR3100' })
    expect(p).toMatchObject({ status: 'draft', name: 'Standard', manufacturer: 'APC', version: 1 })
    expect(p.readiness.missing).toEqual(['u_height', 'width_mm', 'depth_mm', 'height_mm', 'rack_unit_width'])
  })
  it('rejects a duplicate manufacturer+model+variant case-insensitively with existing_id', async () => {
    const e = await codeOf(createMockCabinetApi().create({ manufacturer: 'apc', model: 'netshelter sx ar3300', name: 'STANDARD' }))
    expect(e).toMatchObject({ status: 409, code: 'cabinet_profile_name_taken', detail: { existing_id: 1 } })
  })
  it('publish: 422 cabinet_profile_incomplete lists missing; then publishes', async () => {
    const api = createMockCabinetApi()
    expect(await codeOf(api.publish(2))).toMatchObject({ status: 422, code: 'cabinet_profile_incomplete', detail: { missing: ['depth_mm', 'rack_unit_width'] } })
    const cur = await api.get(2)
    await api.update(2, { expected_updated_at: cur.updated_at, depth_mm: 1200, rack_unit_width: '19in' })
    expect((await api.publish(2)).status).toBe('published')
  })
  it('images are not required to publish', () => {
    expect(readinessOf({ manufacturer: 'a', model: 'b', name: 'c', u_height: 42, width_mm: 1, depth_mm: 1, height_mm: 1, rack_unit_width: '23in' }).ready).toBe(true)
  })
  it('version_conflict on stale expected_updated_at; published stays editable but complete; retired is read-only', async () => {
    const api = createMockCabinetApi()
    expect(await codeOf(api.update(2, { expected_updated_at: '2020-01-01T00:00:00Z', notes: 'x' }))).toMatchObject({ code: 'version_conflict', detail: { current_updated_at: '2026-11-01T15:00:00+00:00', updated_by: 'admin@demo.local' } })
    expect((await api.update(1, { width_mm: 700 })).width_mm).toBe(700)
    expect(await codeOf(api.update(1, { depth_mm: null }))).toMatchObject({ code: 'cabinet_profile_incomplete', detail: { missing: ['depth_mm'] } })
    expect(await codeOf(api.update(3, { notes: 'x' }))).toMatchObject({ status: 409, code: 'cabinet_profile_retired' })
  })
  it('invalid_dimension for usable > outer and rail max > depth', async () => {
    const e = await codeOf(createMockCabinetApi().update(1, { usable_width_mm: 900, rail_depth_max_mm: 2000 }))
    expect(e).toMatchObject({ status: 422, code: 'invalid_dimension', detail: { fields: ['usable_width_mm', 'rail_depth_max_mm'] } })
  })
  it('delete of a superseded profile: 409 cabinet_profile_in_use reason superseded', async () => {
    expect(await codeOf(createMockCabinetApi().remove(3))).toMatchObject({ code: 'cabinet_profile_in_use', detail: { reason: 'superseded', superseded_by: 4 } })
  })
  it('retire → un-retire; invalid transitions; clone = version + 1, supersedes, copies images', async () => {
    const api = createMockCabinetApi()
    expect((await api.retire(1)).status).toBe('retired')
    expect((await api.unretire(1)).status).toBe('published')
    expect(await codeOf(api.retire(2))).toMatchObject({ code: 'invalid_status_transition', detail: { status: 'draft', to: 'retired' } })
    await api.uploadImage(1, 'front', new Blob(['x'], { type: 'image/png' }))
    const c = await api.clone(1)
    expect(c).toMatchObject({ name: 'Standard (copy)', status: 'draft', version: 2, supersedes_cabinet_profile_id: 1 })
    expect(c.front_image).not.toBeNull()
    expect((await api.clone(1)).name).toBe('Standard (copy 2)') // no name: server picks the next free (never 409)
    expect(await codeOf(api.clone(1, 'Standard (copy)'))).toMatchObject({ status: 409, code: 'cabinet_profile_name_taken' })
  })
  it('schema rules come back as a FastAPI validation list (> 0 only, U 1–100); no upper size caps', async () => {
    expect((await createMockCabinetApi().create({ manufacturer: 'big', model: 'b', width_mm: 20000, depth_mm: 50000 })).width_mm).toBe(20000)
    const e = await codeOf(createMockCabinetApi().create({ manufacturer: 'a', model: 'b', width_mm: 0, depth_mm: -1, u_height: 101 }))
    expect(e.status).toBe(422)
    const list = (e.detail as unknown as { type: string; loc: string[] }[])
    expect(Array.isArray(list) ? list.map((i) => i.loc[1]) : null).toEqual(['width_mm', 'depth_mm', 'u_height'])
  })
  it('writes are admin only (403)', async () => {
    const api = createMockCabinetApi({ role: () => 'technician' })
    expect(await codeOf(api.create({ manufacturer: 'a', model: 'b' }))).toMatchObject({ status: 403 })
    expect((await api.list()).length).toBe(4)
  })
})

describe('adapter switch', () => {
  afterEach(() => { CABINET_PROFILE_API.live = false; vi.unstubAllGlobals(); resetCabinetMock() })
  it('tests run on the mock', async () => {
    expect(CABINET_PROFILE_API.live).toBe(false)
    resetCabinetMock()
    expect((await cabinetApi().list({ status: 'published' })).map((p) => p.id)).toEqual([1])
  })
  it('live list pages through X-Total-Count and maps rows tolerantly (image URLs via /api)', async () => {
    CABINET_PROFILE_API.live = true
    const row = (id: number) => ({ id, manufacturer: 'X', model: `M${id}`, name: 'Standard', status: 'draft', rack_unit_width: '21in', front_door: 'glass', rail_type: 'threaded', weight_capacity_kg: 900, rack_count: 0, updated_by: 'a@x',
      front_image: { url: `/cabinet-profile-images/${id}/front?v=ab`, thumb_url: `/cabinet-profile-images/${id}/front?v=ab&variant=thumb`, tex_url: `/cabinet-profile-images/${id}/front?v=ab&variant=tex` }, readiness: { ready: false, missing: ['u_height'] } })
    const total = PAGE + 3
    const fetchMock = vi.fn(async (url: string) => {
      const off = Number(new URL(url, 'http://x').searchParams.get('offset'))
      const n = Math.min(PAGE, total - off)
      return new Response(JSON.stringify(Array.from({ length: n }, (_, i) => row(off + i + 1))), { status: 200, headers: { 'X-Total-Count': String(total) } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const rows = await cabinetApi().list({ status: 'draft', q: 'x' })
    const urls = (fetchMock.mock.calls as unknown as [string][]).map((c) => c[0])
    expect(urls).toEqual([`/api/cabinet-profiles?limit=${PAGE}&offset=0&status=draft&q=x`, `/api/cabinet-profiles?limit=${PAGE}&offset=${PAGE}&status=draft&q=x`])
    expect(rows).toHaveLength(total)
    expect(rows[0]).toMatchObject({ id: 1, rack_unit_width: null, front_door: null, rail_type: 'threaded', weight_capacity_kg: 900, rack_count: 0, updated_by: 'a@x', readiness: { missing: ['u_height'] } })
    expect(rows[0].front_image).toEqual({ url: '/api/cabinet-profile-images/1/front?v=ab', thumb_url: '/api/cabinet-profile-images/1/front?v=ab&variant=thumb', tex_url: '/api/cabinet-profile-images/1/front?v=ab&variant=tex' })
  })
  it('live history reads X-Total-Count', async () => {
    CABINET_PROFILE_API.live = true
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ id: 1, occurred_at: '2026-11-03T12:00:00+00:00', action: 'cabinet_profile.create', actor_email: 'a@x', before: null, after: {} }]), { status: 200, headers: { 'X-Total-Count': '7' } })))
    expect(await cabinetApi().history(5, { limit: 1 })).toMatchObject({ total: 7, items: [{ id: 1 }] })
  })
  it('mock history: newest first, publish gives two events, delete keeps a snapshot', async () => {
    const api = createMockCabinetApi({ rows: [] })
    const p = await api.create({ manufacturer: 'A', model: 'B', u_height: 42, width_mm: 600, depth_mm: 1200, height_mm: 2000, rack_unit_width: '19in' })
    await api.publish(p.id)
    await api.remove(p.id)
    const h = await api.history(p.id)
    expect(h.items.map((e) => e.action)).toEqual(['cabinet_profile.delete', 'cabinet_profile.publish', 'cabinet_profile.update', 'cabinet_profile.create'])
    expect(h.items[0].before).toMatchObject({ manufacturer: 'A' })
    expect(h.items[2].after).toMatchObject({ status: 'published' })
  })
  it('live PATCH sends expected_updated_at; clone sends no name', async () => {
    CABINET_PROFILE_API.live = true
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 1, status: 'draft' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await cabinetApi().update(1, { notes: 'n', expected_updated_at: '2026-11-03T12:00:00' })
    await cabinetApi().clone(1)
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
    expect(calls[0][1]).toMatchObject({ method: 'PATCH', body: JSON.stringify({ notes: 'n', expected_updated_at: '2026-11-03T12:00:00' }) })
    expect(calls[1][0]).toMatch(/\/cabinet-profiles\/1\/clone$/)
    expect(calls[1][1].body).toBe('{}') // no name: the server picks "(copy N)"
  })
  it('cabinetError reads structured detail', () => {
    const e = new ApiError(409, 'm', { detail: { code: 'cabinet_profile_in_use', reason: 'superseded' } })
    expect(cabinetError(e)).toMatchObject({ code: 'cabinet_profile_in_use', detail: { reason: 'superseded' } })
    expect(toCabinetProfile({ id: '3' }).id).toBe(3)
  })
})
