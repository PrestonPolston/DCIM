import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { setCsrfToken } from '../api/client'
import { friendlyMessage } from '../api/errors'
import { checklist, emptyProfileForm, imageProblem, isPlaceable, issueLabel, needsReview, toUiProfile, usabilityOf, type ProfileListItem } from '../api/profiles'
import { installMockApi, PROFILES, resetAuth, seedDb } from '../test/mockApi'
import { renderWithProviders } from '../test/render'

const FLAGGED = { id: 10, device_type_id: 2, name: 'Rev B', is_default: false, u_height: 1, is_full_depth: false, status: 'published', usable: false, usable_issue: 'rear_image_missing', usable_issues: ['rear_image_missing'], rear_image: null }

describe('profile usability adapter (profile_not_usable contract, 5238001)', () => {
  it('reads API fields, else derives from rear_image / orientation', () => {
    expect(usabilityOf({ usable: false, usable_issues: ['rear_image_missing', 'orientation_missing'] })).toEqual({ usable: false, issues: ['rear_image_missing', 'orientation_missing'] })
    expect(usabilityOf({ usable: true, usable_issues: [] })).toEqual({ usable: true, issues: [] })
    expect(usabilityOf({ status: 'published', rear_image: null }).issues).toEqual(['rear_image_missing'])
    expect(usabilityOf({ status: 'published', rear_image: { url: '/r', thumb_url: '/t' } }).usable).toBe(true)
    expect(usabilityOf({ status: 'published' }).usable).toBe(true) // older server without the key: no false flag
    expect(usabilityOf({ status: 'published', asset_type: 'switch', orientation: null, rear_image: { url: '/r', thumb_url: '/t' } }).issues).toEqual(['orientation_missing'])
    expect(usabilityOf({ status: 'published', asset_type: 'switch', rear_image: { url: '/r', thumb_url: '/t' } }).usable).toBe(true) // no orientation field yet
    expect(issueLabel('rear_image_missing')).toBe('Needs rear image')
    expect(issueLabel('orientation_missing')).toBe('Needs orientation')
  })
  it('flagged published profiles are not placeable and are "Needs review"', () => {
    const p = toUiProfile({ manufacturer: 'Arista', model: '7050', ...FLAGGED } as unknown as ProfileListItem)
    expect(needsReview(p)).toBe(true)
    expect(isPlaceable(p)).toBe(false)
  })
  it('422 profile_not_usable → upload-rear copy', () => {
    expect(friendlyMessage({ code: 'profile_not_usable', issues: ['rear_image_missing'] }, 422)).toMatch(/^Upload a rear image for this profile first/)
    expect(friendlyMessage({ code: 'profile_not_usable', reason: 'orientation_missing' }, 422)).toMatch(/orientation/)
  })
})

describe('Profiles page: Needs review worklist', () => {
  beforeEach(() => { resetAuth(); setCsrfToken('csrf-1'); localStorage.clear(); PROFILES.push(FLAGGED as never); installMockApi(seedDb()) })
  afterEach(() => { PROFILES.splice(PROFILES.findIndex((p) => p.id === 10), 1) })

  it('shows the badge, filters the worklist and offers Upload rear image', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles')
    expect(await screen.findByText(/Needs review · Needs rear image/)).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: /Needs review/ }))
    const rows = within(screen.getByRole('table', { name: 'Profiles' })).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('Rev B')
    await user.click(within(rows[0]).getByText('⋯'))
    expect(within(rows[0]).getByRole('button', { name: 'Upload rear image' })).toBeInTheDocument()
  })
})

describe('Bulk image upload', () => {
  let calls: ReturnType<typeof installMockApi>
  beforeEach(() => { resetAuth(); setCsrfToken('csrf-1'); localStorage.clear(); calls = installMockApi(seedDb()) })

  it('matches files by name, previews problems, uploads the matched ones via PUT …/images/{face}', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles?bulk=1')
    const dlg = await screen.findByRole('dialog', { name: 'Upload profile images' })
    const f = (n: string) => new File(['x'], n, { type: 'image/jpeg' })
    await user.upload(within(dlg).getByLabelText('Choose image files'), [f('Dell_R650_front.jpg'), f('Arista_7050X_rear.jpg'), f('IMG_0001.jpg')])
    const table = await within(dlg).findByRole('table', { name: 'Match preview' })
    expect(within(table).getByText('Name must end in _front or _rear')).toBeInTheDocument()
    expect((within(table).getByLabelText('Profile for Dell_R650_front.jpg') as HTMLSelectElement).value).toBe('7')
    await user.click(within(dlg).getByRole('button', { name: 'Upload 2 images' }))
    await within(dlg).findAllByText(/✓ Uploaded/)
    const puts = calls.filter((c) => c.method === 'PUT').map((c) => c.url)
    expect(puts.sort()).toEqual(['/device-types/1/profiles/7/images/front', '/device-types/2/profiles/9/images/rear'])
    expect(within(table).getByText('Skipped')).toBeInTheDocument()
  })

  it('HEIC/HEIF: per-file error in the preview table, never uploaded; single inputs say the same', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles?bulk=1')
    const dlg = await screen.findByRole('dialog', { name: 'Upload profile images' })
    await user.upload(within(dlg).getByLabelText('Choose image files'), [new File(['x'], 'Dell_R650_front.HEIC', { type: 'image/heic' }), new File(['x'], 'Arista_7050X_rear.heif', { type: '' })])
    const table = await within(dlg).findByRole('table', { name: 'Match preview' })
    expect(within(table).getAllByText("HEIC isn't supported yet. Export as JPEG or PNG.")).toHaveLength(2)
    expect(imageProblem({ name: 'a.heic', type: 'image/heic', size: 10 })).toBe("HEIC isn't supported yet. Export as JPEG or PNG.")
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })
})

describe('Profile orientation (D58, flag on)', () => {
  it('orientation blocks the switch checklist only; racing 409 codes have copy', () => {
    const sw = checklist(emptyProfileForm({ assetType: 'switch' }))
    expect(sw.find((i) => i.key === 'orientation')?.ok).toBe(false)
    expect(checklist(emptyProfileForm({ assetType: 'switch', orientation: 'port_front' })).find((i) => i.key === 'orientation')?.ok).toBe(true)
    expect(checklist(emptyProfileForm({ assetType: 'server' })).some((i) => i.key === 'orientation')).toBe(false)
    expect(friendlyMessage({ code: 'ru_slot_taken' }, 409)).toMatch(/just placed/)
    expect(usabilityOf({ status: 'published', usable: false, usable_issues: ['rear_image_missing', 'orientation_missing'] }).issues[0]).toBe('rear_image_missing')
  })

  const NO_O = { id: 20, device_type_id: 2, name: 'Old switch', is_default: false, u_height: 1, is_full_depth: false, status: 'published', asset_type: 'switch', effective_asset_type: 'switch', orientation: null, usable: false, usable_issue: 'orientation_missing', usable_issues: ['orientation_missing'], device_count: 2 }
  const PORT = { id: 21, device_type_id: 2, name: '7050X (Port Front)', is_default: false, u_height: 1, is_full_depth: false, status: 'published', asset_type: 'switch', effective_asset_type: 'switch', orientation: 'port_front', usable: true, usable_issue: null, usable_issues: [], device_count: 0 }
  let calls: ReturnType<typeof installMockApi>
  beforeEach(() => { resetAuth(); setCsrfToken('csrf-1'); localStorage.clear(); PROFILES.push(NO_O as never, PORT as never); calls = installMockApi(seedDb()) })
  afterEach(() => { for (const id of [20, 21]) PROFILES.splice(PROFILES.findIndex((p) => p.id === id), 1) })
  const row = (name: string) => within(screen.getByRole('table', { name: 'Profiles' })).getAllByRole('row').find((r) => r.textContent?.includes(name))!

  it('badges + ?orientation filter; fills a missing orientation with PATCH', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles')
    expect(await screen.findByText(/Needs review · Needs orientation/)).toBeInTheDocument()
    expect(within(row('7050X (Port Front)')).getByText('⇄ PORT FRONT')).toBeInTheDocument()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Orientation' }), 'port_front')
    expect(within(screen.getByRole('table', { name: 'Profiles' })).getAllByRole('row').slice(1)).toHaveLength(1)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Orientation' }), '')
    await user.click(within(row('Old switch')).getByText('⋯'))
    await user.selectOptions(within(row('Old switch')).getByRole('combobox', { name: /Orientation for/ }), 'power_front')
    await user.click(within(row('Old switch')).getByRole('button', { name: 'Set orientation' }))
    await within(row('Old switch')).findByText('Orientation set to Power front.')
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.url).toBe('/device-types/2/profiles/20')
    expect(patch.body).toEqual({ orientation: 'power_front' })
  })

  it('Add orientation variant clones with swap_faces and the "(Power Front)" name', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles')
    await screen.findByText('⇄ PORT FRONT')
    await user.click(within(row('7050X (Port Front)')).getByText('⋯'))
    await user.click(within(row('7050X (Port Front)')).getByRole('button', { name: 'Add orientation variant' }))
    expect(screen.getByLabelText('Variant name')).toHaveValue('7050X (Power Front)')
    await user.click(screen.getByRole('button', { name: 'Create draft' }))
    await screen.findByText(/Draft 7050X \(Power Front\) created/)
    const c = calls.find((x) => x.method === 'POST' && x.url === '/profiles/21/clone')!
    expect(c.body).toEqual({ name: '7050X (Power Front)', swap_faces: true })
  })
})
