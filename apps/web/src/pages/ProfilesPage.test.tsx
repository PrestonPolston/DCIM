import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { setCsrfToken } from '../api/client'
import { installMockApi, resetAuth, seedDb, type Db } from '../test/mockApi'
import { renderWithProviders } from '../test/render'

let db: Db
let calls: ReturnType<typeof installMockApi>
beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  db = seedDb()
  calls = installMockApi(db)
})

describe('Profiles screen', () => {
  it('lists GET /profiles with state, counts and filters by state', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles')
    const table = await screen.findByRole('table', { name: 'Profiles' })
    expect(await within(table).findAllByText('Dell R650')).toHaveLength(2)
    expect(within(table).getByText('✎ Draft')).toBeInTheDocument()
    expect(within(table).getAllByText('◇ Needs image', { exact: false }).length).toBe(3)
    await user.click(screen.getByRole('button', { name: 'Draft' }))
    await waitFor(() => expect(within(screen.getByRole('table', { name: 'Profiles' })).getAllByRole('row')).toHaveLength(2))
    expect(calls.some((c) => c.url.startsWith('/profiles?status=draft'))).toBe(true)
  })

  it('Add profile: live preview, SVG rejected, checklist, Save draft POSTs the model then the profile', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles')
    await user.click(await screen.findByRole('button', { name: '＋ Add profile' }))
    const dlg = screen.getByRole('dialog', { name: 'New profile' })
    const save = within(dlg).getByRole('button', { name: 'Save draft' })
    expect(save).toBeDisabled()
    await user.type(within(dlg).getByLabelText('Manufacturer'), 'HPE')
    await user.type(within(dlg).getByLabelText('Model'), 'DL380')
    await user.clear(within(dlg).getByLabelText('U height'))
    await user.type(within(dlg).getByLabelText('U height'), '2')
    expect(save).toBeEnabled()
    expect(within(dlg).getByTestId('profile-preview').style.height).toBe('88px')
    expect(within(dlg).getByTestId('fallback-front')).toBeInTheDocument()
    const svg = new File(['<svg/>'], 'front.svg', { type: 'image/svg+xml' })
    fireEvent.change(within(dlg).getByLabelText('Front image *'), { target: { files: [svg] } })
    expect(await within(dlg).findByText("SVG isn't supported. Export a PNG.")).toBeInTheDocument()
    const list = within(dlg).getByRole('list', { name: 'Publish checklist' })
    expect(within(list).getByText(/Front image/).closest('li')).toHaveClass('bad')
    await user.click(save)
    expect(await within(dlg).findByRole('status')).toHaveTextContent('Saved draft HPE DL380 · Default.')
    const posts = calls.filter((c) => c.method === 'POST')
    expect(posts.map((c) => c.url)).toEqual(['/device-types', expect.stringMatching(/^\/device-types\/\d+\/profiles$/)])
    expect(posts[0].body).toMatchObject({ manufacturer: 'HPE', name: 'DL380', u_height: 2, is_full_depth: true })
    expect(posts[1].body).toMatchObject({ name: 'Default', is_full_depth: true, mounting: 'rack_19in' })
  })

  it('Publish saves the draft, uploads the front image raw, then shows the server missing[] on 422', async () => {
    const user = userEvent.setup()
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } })
    calls = installMockApi(db, (method, path) => {
      if (method === 'PUT' && /\/images\/front$/.test(path)) return json({ face: 'front' }, 201)
      if (method === 'POST' && /^\/profiles\/\d+\/publish$/.test(path))
        return json({ detail: { code: 'profile_not_ready', message: 'Profile is not ready', missing: ['power_type', 'width_mm'] } }, 422)
      return undefined
    })
    renderWithProviders(<App />, '/profiles?new=1')
    const dlg = await screen.findByRole('dialog', { name: 'New profile' })
    await user.type(within(dlg).getByLabelText('Manufacturer'), 'HPE')
    await user.type(within(dlg).getByLabelText('Model'), 'DL380')
    await user.selectOptions(within(dlg).getByLabelText('Asset type'), 'server')
    const png = new File([new Uint8Array([137, 80, 78, 71])], 'front.png', { type: 'image/png' })
    fireEvent.change(within(dlg).getByLabelText('Front image *'), { target: { files: [png] } })
    await user.click(within(dlg).getByRole('button', { name: 'Publish' }))
    expect(await within(dlg).findByRole('alert')).toHaveTextContent('Missing: power type (AC/DC), width.')
    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.url).toMatch(/^\/device-types\/\d+\/profiles\/\d+\/images\/front$/)
    expect(put.body).toBeInstanceOf(File)
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.url).at(-1)).toMatch(/^\/profiles\/\d+\/publish$/)
    expect(within(within(dlg).getByRole('list', { name: 'Publish checklist' })).getByText(/Power type/).closest('li')).toHaveClass('bad')
    // Draft already saved: no second profile POST on retry.
    await user.click(within(dlg).getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && /\/device-types\/\d+\/profiles$/.test(c.url))).toHaveLength(1))
  })

  it('row menu: Publish a ready draft (admin) via POST /profiles/{id}/publish', async () => {
    const user = userEvent.setup()
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } })
    calls = installMockApi(db, (method, path) => (method === 'POST' && path === '/profiles/8/publish' ? json({ id: 8 }) : undefined))
    renderWithProviders(<App />, '/profiles?status=draft')
    const table = await screen.findByRole('table', { name: 'Profiles' })
    await user.click(within(table).getByLabelText(/^Actions for /))
    await user.click(within(table).getByRole('button', { name: 'Publish' }))
    expect(await within(table).findByText(/^Published /)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.url === '/profiles/8/publish')).toBe(true)
  })

  it('warns about a duplicate model', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/profiles?new=1&manufacturer=Dell&model=R650')
    const dlg = await screen.findByRole('dialog', { name: 'New profile' })
    expect(within(dlg).getByLabelText('Manufacturer')).toHaveValue('Dell')
    expect(await within(dlg).findByText(/Dell R650 already exists/)).toBeInTheDocument()
    await user.click(within(dlg).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('read-only users get no Add profile', async () => {
    resetAuth({ role: 'read-only' })
    renderWithProviders(<App />, '/profiles')
    await screen.findByRole('table', { name: 'Profiles' })
    expect(screen.queryByRole('button', { name: '＋ Add profile' })).toBeNull()
  })
})

describe('CSV import dry run', () => {
  it('flags placing rows without a profile with Create profile / Finish draft links', async () => {
    db['device-types'].push({ id: 3, manufacturer: 'HPE', name: 'DL380', u_height: 2, is_full_depth: true })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/import')
    const csv = 'host_name,manufacturer,model,rack_id,position_u\nok-01,Dell,R650,12,20\nnew-01,Cisco,C9300,12,30\nfree-01,,,,\n'
    const file = new File([csv], 'devices.csv', { type: 'text/csv' })
    await user.upload(await screen.findByLabelText('CSV file'), file)
    await user.click(screen.getByRole('button', { name: 'Dry run' }))
    const errs = await screen.findByRole('table', { name: 'Row errors' })
    expect(within(errs).getByText('3')).toBeInTheDocument()
    expect(within(errs).getByRole('link', { name: 'Create profile' })).toHaveAttribute('href', '/profiles?new=1&manufacturer=Cisco&model=C9300')
    expect(screen.getByText("1 row need 1 profile that aren't published.")).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/devices/import?dry_run=true')!.body).toBe(csv)
  })
})
