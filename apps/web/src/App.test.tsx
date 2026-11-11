import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { installMockApi, resetAuth, seedDb, type Db } from './test/mockApi'
import { setCsrfToken } from './api/client'
import { renderWithProviders } from './test/render'

let db: Db
let calls: ReturnType<typeof installMockApi>
beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  db = seedDb()
  calls = installMockApi(db)
})

describe('hall floor plan and tree', () => {
  it('hall route shows cabinet tiles with usage', async () => {
    renderWithProviders(<App />, '/halls/1')
    const tile = await screen.findByRole('link', { name: /Cabinet R12, 2 of 53 RU used, 51 free, front faces S \(default for odd rows\)/ })
    expect(screen.getByRole('link', { name: /Cabinet R13, 0 of 42 RU used, 42 free/ })).toHaveClass('empty')
    expect(tile).toHaveAttribute('href', '/halls/1/cabinets/12')
    expect(screen.getByLabelText('Center aisle')).toBeInTheDocument()
  })

  it('layout settings are per hall in localStorage and re-derive facing', async () => {
    localStorage.clear()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1')
    await screen.findByRole('link', { name: /Cabinet R12/ })
    await user.click(screen.getByText('Layout ▾'))
    await user.selectOptions(screen.getByLabelText('Odd rows side'), 'end')
    expect(screen.getByRole('link', { name: /Cabinet R12/ })).toHaveAccessibleName(/front faces N/)
    expect(JSON.parse(localStorage.getItem('dcim.hall.1.layout')!)).toMatchObject({ oddSide: 'end' })
    await user.click(screen.getByRole('button', { name: 'Reset to default' }))
    expect(localStorage.getItem('dcim.hall.1.layout')).toBeNull()
  })

  it('tree drills Data Hall › Row › Cabinet › RU › Device', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1')
    const tree = await screen.findByRole('tree', { name: 'Data halls' })
    await user.click(await within(tree).findByRole('button', { name: 'Expand Row 3' }))
    await user.click(within(tree).getByRole('button', { name: 'Expand R12' }))
    expect(await within(tree).findByText('web-01')).toBeInTheDocument()
    expect(within(tree).getByText('RU 2–3')).toBeInTheDocument()
    await user.click(within(tree).getByRole('link', { name: /R12/ }))
    expect(await screen.findByRole('heading', { name: 'Cabinet R12' })).toBeInTheDocument()
  })
})

describe('cabinet placement', () => {
  it('renders the elevation from /racks/{id}/elevation', async () => {
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    expect(await screen.findByRole('button', { name: /web-01, Active, U2 to U3, front/ })).toBeInTheDocument()
    expect(calls.some((c) => c.url === '/racks/12/elevation')).toBe(true)
    expect(screen.getByRole('button', { name: 'Front (aisle)' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Rear (back of row)' })).toBeInTheDocument()
    expect(await screen.findByText(/front faces S → center aisle/)).toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('unplaced=true'))).toBe(true)
  })

  it('drags a published profile onto a valid RU and POSTs the new device with profile_id', async () => {
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    const palette = await screen.findByRole('region', { name: 'Profiles' })
    const item = await within(palette).findByRole('button', { name: 'Dell R650, 2U · Full' })
    expect(within(palette).queryByRole('button', { name: /R650 GPU/ })).toBeNull() // drafts aren't listed
    expect(within(palette).getByRole('link', { name: /1 drafts need finishing/ })).toHaveAttribute('href', '/profiles?status=draft')
    const dt = { setData: () => {}, effectAllowed: '', dropEffect: '' }
    fireEvent.dragStart(item, { dataTransfer: dt })
    // R650 is 2U full-depth: RU 1 would overlap web-01 (RU2-3), RU 52 fits, RU 53 exceeds
    expect(screen.getByTestId('slot-front-1')).toHaveAccessibleName('Cannot place at RU 1: overlaps web-01')
    expect(screen.getByTestId('slot-front-53')).toHaveAccessibleName('Cannot place at RU 53: exceeds RU53')
    expect(screen.getByTestId('slot-front-52')).toHaveClass('drop-ok')
    const ok = screen.getByTestId('slot-front-8')
    expect(ok).toHaveClass('drop-ok')
    fireEvent.dragOver(ok, { dataTransfer: dt })
    fireEvent.drop(ok, { dataTransfer: dt })
    const user = userEvent.setup()
    const dialog = screen.getByRole('dialog', { name: 'Place device' })
    expect(within(dialog).getByText('R12 · RU 8 · Front')).toBeInTheDocument()
    expect(within(dialog).getByRole('group', { name: 'Profile' })).toHaveTextContent('Dell R650')
    expect(within(dialog).queryByLabelText('Model')).toBeNull()
    await user.type(within(dialog).getByLabelText('Hostname'), 'web-02')
    await user.click(within(dialog).getByRole('button', { name: 'Place device' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({ host_name: 'web-02', profile_id: 7, device_type_id: 1, rack_id: 12, position_u: 8, face: 'front' })
    expect(await screen.findByRole('button', { name: /web-02, Install, U8 to U9/ })).toBeInTheDocument()
  })

  it('click alternative: select an unplaced device, click a RU, PATCH, and show 409 detail', async () => {
    installMockApi(db, (m) =>
      m === 'PATCH' ? new Response(JSON.stringify({ detail: "Placement overlaps device 'x'" }), { status: 409 }) : undefined,
    )
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    await user.click(await screen.findByRole('button', { name: /db-01 · 1U/ }))
    // 7050X is half-depth; full-depth web-01 still occupies rear RU 2-3
    await user.click(screen.getByRole('button', { name: 'Rear (back of row)' }))
    expect(screen.queryByTestId('slot-rear-2')).toBeNull()
    expect(screen.getByTestId('slot-rear-1')).toHaveClass('drop-ok')
    await user.click(screen.getByTestId('slot-rear-1'))
    const dialog = screen.getByRole('dialog', { name: 'Place device' })
    await user.click(within(dialog).getByRole('button', { name: 'Move device' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent("Placement overlaps device 'x'")
  })
})

describe('profile required for placement', () => {
  it('has no Unknown device item; an empty RU asks Choose profile first, then places with profile_id', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    await screen.findByRole('heading', { name: 'Cabinet R12' })
    expect(screen.queryByRole('button', { name: /Unknown device/ })).toBeNull()
    await user.click(screen.getByTestId('slot-front-1'))
    const sheet = screen.getByRole('dialog', { name: 'Choose profile' })
    await user.click(await within(sheet).findByRole('button', { name: 'Arista 7050X, 1U · Half' }))
    const dialog = screen.getByRole('dialog', { name: 'Place device' })
    await user.type(within(dialog).getByLabelText('Hostname'), 'sw-09')
    await user.click(within(dialog).getByRole('button', { name: 'Place device' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({ host_name: 'sw-09', profile_id: 9, device_type_id: 2, rack_id: 12, position_u: 1 })
  })

  it('shows friendly copy for 422 profile_not_published with missing[]', async () => {
    calls = installMockApi(db, (method, path) =>
      method === 'POST' && path === '/devices'
        ? new Response(JSON.stringify({ detail: { code: 'profile_not_published', message: 'raw', missing: ['width_mm'] } }), { status: 422, headers: { 'Content-Type': 'application/json' } })
        : undefined)
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    await user.click(await screen.findByTestId('slot-front-1'))
    await user.click(await within(screen.getByRole('dialog', { name: 'Choose profile' })).findByRole('button', { name: 'Arista 7050X, 1U · Half' }))
    const dialog = screen.getByRole('dialog', { name: 'Place device' })
    await user.type(within(dialog).getByLabelText('Hostname'), 'sw-09')
    await user.click(within(dialog).getByRole('button', { name: 'Place device' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent("This profile isn't published yet (or was retired). Pick a published profile. Missing: width_mm.")
  })

  it('a placed device flagged needs_review draws 1U on both faces with the Needs profile badge', async () => {
    db.devices.push({ id: 3, host_name: 'old-01', status: 'active', serial_number: 'X', rack_id: 12, position_u: 10, face: 'front', device_type_id: null, needs_review: true, needs_review_reason: 'placed_without_profile' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    const block = await screen.findByRole('button', { name: /^old-01, Active, U10, front, serial X, needs profile$/ })
    expect(within(block).getByText('Needs profile', { exact: false })).toBeInTheDocument()
    expect(block.title).toContain('Placed without a profile. Choose a profile.')
    await user.click(screen.getByRole('button', { name: /^Rear/ }))
    expect(await screen.findByRole('button', { name: /^old-01, Active, U10, front \(shown from rear\)/ })).toBeInTheDocument()
  })
})

describe('routes', () => {
  it('import page shows the stepper', async () => {
    renderWithProviders(<App />, '/import')
    expect(await screen.findByRole('heading', { name: 'CSV import' })).toBeInTheDocument()
  })
})
