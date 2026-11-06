import { describe, expect, it } from 'vitest'
import {
  apiAssetUrl, checklist, canSaveDraft, emptyProfileForm, frontImageOf, heightWarning, imageProblem, matches, parsePlacing, placementBody,
  placingOf, specLine, toUiProfile, type ProfileListItem,
} from './profiles'
import { errorDetail, friendlyMessage } from './errors'
import { categoryOf } from '../lib/rowFront'
import { classifyRowError, rowModel } from '../lib/importErrors'

const item: ProfileListItem = {
  id: 7, name: 'Default', device_type_id: 1, manufacturer: 'Dell', model: 'R650', u_height: 2, is_full_depth: true, is_default: true,
  width_mm: 482, height_mm: 87, depth_mm: 750, power_type: 'AC', asset_type: null, effective_asset_type: 'server', status: 'published', device_count: 3,
  front_image: { url: '/img/7', thumb_url: '/img/7?t' },
}

describe('profile adapter (the only place API profile fields are read)', () => {
  it('maps GET /profiles items', () => {
    const p = toUiProfile(item)
    expect(p).toMatchObject({ id: 7, deviceTypeId: 1, manufacturer: 'Dell', model: 'R650', uHeight: 2, isFullDepth: true, assetType: 'server', status: 'published', deviceCount: 3 })
    expect(p.frontImage).toEqual({ url: '/api/img/7', thumb_url: '/api/img/7?t' })
    expect(specLine(p)).toBe('2U · Full')
  })
  it('images: {url, thumb_url} from front_image or effective_front_image; front_image_url ignored', () => {
    expect(frontImageOf({ effective_front_image: { url: 'a', thumb_url: 'b' } })).toEqual({ url: 'a', thumb_url: 'b' })
    expect(frontImageOf({ front_image: null, front_image_url: '/x' })).toBeNull()
  })
  it('drag payload carries a profile; placement body sends profile_id (+ its type)', () => {
    const pl = placingOf(toUiProfile(item))
    expect(parsePlacing(JSON.stringify(pl))).toEqual(pl)
    expect(parsePlacing('type:1')).toBeNull()
    expect(placementBody(pl)).toEqual({ profile_id: 7, device_type_id: 1 })
  })
  it('local filters: published-only palette, U and depth chips, unknown asset type', () => {
    const p = toUiProfile(item)
    expect(matches(p, {})).toBe(true)
    expect(matches({ ...p, status: 'draft' }, {})).toBe(false)
    expect(matches(p, { u: '4+' })).toBe(false)
    expect(matches(p, { depth: 'half' })).toBe(false)
    expect(matches({ ...p, assetType: null }, { assetType: 'unknown', status: 'all' })).toBe(true)
  })
})

describe('Add profile rules', () => {
  it('Save draft needs only manufacturer, model, name; checklist lists the publish items', () => {
    const f = emptyProfileForm({ manufacturer: 'Dell', model: 'R760' })
    expect(canSaveDraft(f)).toBe(true)
    expect(canSaveDraft({ ...f, name: ' ' })).toBe(false)
    const c = checklist(f)
    expect(c.filter((i) => !i.ok).map((i) => i.label)).toEqual(['Asset type', 'Width / Height / Depth (mm)', 'Front image', 'Rear image', 'Power type (AC/DC)'])
    expect(checklist(emptyProfileForm({ rearImage: new File(['x'], 'r.png', { type: 'image/png' }) }), ['rear_image']).find((i) => i.key === 'rear_image')!.ok).toBe(false) // server missing[] wins
    expect(checklist({ ...f, widthMm: '1', heightMm: '1', depthMm: '1', powerType: 'AC', assetType: 'server' }, ['front_image']).filter((i) => !i.ok).map((i) => i.key)).toEqual(['front_image', 'rear_image'])
    expect(checklist({ ...f, uHeight: '0' }).find((i) => i.key === 'u_height')!.ok).toBe(false)
    expect(checklist({ ...f, uHeight: '0', mounting: 'zero_u' }).find((i) => i.key === 'u_height')!.ok).toBe(true)
    expect(heightWarning({ ...f, uHeight: '2', heightMm: '120' })).toContain('more than 10%')
    expect(heightWarning({ ...f, uHeight: '2', heightMm: '87' })).toBeNull()
  })
  it('images: PNG/JPEG/WebP, ≤ 2 MiB, ≤ 4096 px, SVG rejected', () => {
    expect(imageProblem({ name: 'a.svg', type: 'image/svg+xml', size: 10 })).toBe("SVG isn't supported. Export a PNG.")
    expect(imageProblem({ name: 'a.gif', type: 'image/gif', size: 10 })).toBe('Use a PNG, JPEG or WebP image.')
    expect(imageProblem({ name: 'a.png', type: 'image/png', size: 3 * 1024 * 1024 })).toBe('The image is larger than 2 MiB.')
    expect(imageProblem({ name: 'a.webp', type: 'image/webp', size: 10 }, { w: 5000, h: 100 })).toContain('4096')
    expect(imageProblem({ name: 'a.jpg', type: 'image/jpeg', size: 10 }, { w: 4096, h: 4096 })).toBeNull()
  })
})

describe('error codes (apps/api a289079)', () => {
  const f = (code: string, status: number, missing?: string[]) => friendlyMessage(errorDetail({ detail: { code, message: 'raw', missing } })!, status)
  it('has friendly copy for each code', () => {
    expect(f('profile_required', 422)).toMatch(/^Choose a profile/)
    expect(f('profile_not_published', 422, ['width_mm'])).toBe("This profile isn't published yet (or was retired). Pick a published profile. Missing: width_mm.")
    expect(f('profile_not_published', 409)).toMatch(/^This device's profile isn't published/)
    expect(f('placed_without_profile', 409)).toMatch(/^This device was placed without a profile/)
    expect(f('profile_in_use', 409)).toMatch(/Create a new version or retire it/)
    expect(f('device_has_connections', 409)).toMatch(/Delete its connections first/)
    expect(f('port_in_use', 409)).toMatch(/already connected/)
    expect(f('self_connection', 422)).toMatch(/itself/)
    expect(f('cable_label_conflict', 409)).toMatch(/different label/)
    expect(f('something_new', 409)).toBeNull()
  })
})

describe('asset types → fallback fronts (D34)', () => {
  it('maps every value', () => {
    expect(['server', 'storage', 'switch', 'router', 'firewall', 'patch_panel', 'pdu', 'blank', 'shelf', 'other'].map(categoryOf))
      .toEqual(['server', 'server', 'switch', 'switch', 'switch', 'patch', 'pdu', 'other', 'other', 'other'])
  })
})

describe('CSV row errors', () => {
  it('classifies profile errors and reads manufacturer/model for the line', () => {
    expect(classifyRowError("Unknown device type 'HPE DL380'")).toBe('profile_required')
    expect(classifyRowError('Placing a device requires a profile')).toBe('profile_required')
    expect(classifyRowError('host_name: required')).toBe('other')
    expect(rowModel([['host_name', 'manufacturer', 'model'], ['a', 'HPE', 'DL380']], 2)).toEqual({ manufacturer: 'HPE', model: 'DL380' })
  })
})

describe('apiAssetUrl', () => {
  it('routes API-root image URLs through the API base, once', () => {
    expect(apiAssetUrl('/profile-images/12/front?v=1&variant=thumb')).toBe('/api/profile-images/12/front?v=1&variant=thumb')
    expect(apiAssetUrl('/api/profile-images/12/front')).toBe('/api/profile-images/12/front')
    expect(apiAssetUrl('https://cdn.example.com/a.png')).toBe('https://cdn.example.com/a.png')
    expect(frontImageOf({ front_image: frontImageOf({ front_image: { url: '/x' } }) })).toEqual({ url: '/api/x', thumb_url: '/api/x' })
  })
})
