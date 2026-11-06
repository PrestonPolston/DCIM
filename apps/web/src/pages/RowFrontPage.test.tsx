import { beforeEach, describe, expect, it } from 'vitest'
import { act, createEvent, fireEvent, screen, waitFor, within } from '@testing-library/react'
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
  localStorage.clear()
  db = seedDb()
  calls = installMockApi(db)
})

const WEB = /^web-01, Active, cabinet R12, RU 2 to 3, front$/
function dnd(type: 'dragOver' | 'drop', el: Element, clientY: number) {
  const ev = createEvent[type](el)
  Object.defineProperty(ev, 'clientY', { value: clientY })
  fireEvent(el, ev)
}
const patches = () => calls.filter((c) => c.method === 'PATCH')

describe('Row front view', () => {
  it('opens from the tree row node and shows a mixed 53U/42U row at Fit (L0)', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1')
    await user.click((await screen.findAllByRole('link', { name: 'Row 3' }))[0])
    const grid = await screen.findByRole('grid', { name: 'Row cabinets, front view' })
    expect(screen.getByText('Fit · 6 px/RU')).toBeInTheDocument()
    expect(screen.getByLabelText('Left is W, right is E')).toBeInTheDocument()
    const cabs = within(grid).getAllByRole('row').map((r) => r.getAttribute('aria-label'))
    expect(cabs).toEqual(['Cabinet R12, 53U', 'Cabinet R13, 42U'])
    expect(screen.getByTitle('No rails: 42U cabinet').style.height).toBe(`${11 * 6}px`)
    const web = within(grid).getByRole('gridcell', { name: WEB })
    expect(web.querySelector('.df-label')).toBeNull() // L0: no text
    expect(web.querySelector('[data-testid=fallback-front]')).toBeNull()
    expect(screen.getByText(/Row 3 · 2 cabinets · 2\/95 RU used/)).toBeInTheDocument()
  })

  it('L2 detail: hostname, fallback front with placeholder; click selects into the side panel; Open cabinet', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    const web = await screen.findByRole('gridcell', { name: WEB })
    expect(within(web).getByText('web-01')).toBeInTheDocument()
    expect(web.querySelector('[data-testid=fallback-front]')!.getAttribute('data-category')).toBe('other') // interim: no asset_type in the API, 'Dell R650' has no keyword
    expect(within(web).getByTitle('Generic image: no front image for this model')).toBeInTheDocument()
    await user.click(web)
    const panel = screen.getByRole('complementary', { name: 'Device web-01' })
    expect(within(panel).getByText('R12 · RU2–3 · Front')).toBeInTheDocument()
    expect(web).toHaveAttribute('aria-selected', 'true')
    await user.click(within(panel).getByRole('button', { name: 'Open cabinet ›' }))
    expect(await screen.findByRole('heading', { name: 'Cabinet R12' })).toBeInTheDocument()
  })

  it('keyboard: arrows move across cabinets, Enter opens the elevation', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    const web = await screen.findByRole('gridcell', { name: WEB })
    act(() => web.focus())
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('gridcell', { name: 'Empty, cabinet R13, RU 1 to 42, 42 free' })).toHaveFocus()
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('gridcell', { name: 'Empty, cabinet R12, RU 4 to 53, 50 free' })).toHaveFocus()
    await user.keyboard('{ArrowDown}{Enter}')
    expect(await screen.findByRole('heading', { name: 'Cabinet R12' })).toBeInTheDocument()
  })

  it('keyboard move across cabinets: confirm, PATCH, then Undo', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    const web = await screen.findByRole('gridcell', { name: WEB })
    act(() => web.focus())
    await user.keyboard('m{ArrowRight}{ArrowUp}{Enter}')
    const dlg = screen.getByRole('dialog', { name: 'Confirm move' })
    expect(within(dlg).getByText('Move web-01: R12 RU2 Front → R13 RU3 Front')).toBeInTheDocument()
    await user.click(within(dlg).getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(patches()).toHaveLength(1))
    expect(patches()[0]).toMatchObject({ url: '/devices/1', body: { rack_id: 13, position_u: 3, face: 'front' }, csrf: 'csrf-1' })
    await user.click(await screen.findByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(patches()).toHaveLength(2))
    expect(patches()[1].body).toEqual({ rack_id: 12, position_u: 2, face: 'front' })
  })

  it('drag across cabinets shows the fit ghost and confirms; a 409 shows the server message', async () => {
    const user = userEvent.setup()
    calls = installMockApi(db, (method, path) =>
      method === 'PATCH' && path === '/devices/1'
        ? new Response(JSON.stringify({ detail: { code: 'overlap', message: 'Overlaps db-03 at RU10' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })
        : undefined)
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    const web = await screen.findByRole('gridcell', { name: WEB })
    expect(web).toHaveAttribute('draggable', 'true')
    const r13 = screen.getByTestId('cabinet-13')
    fireEvent.dragStart(web, { dataTransfer: { setData: () => {}, effectAllowed: '' } })
    // top RU 11 of a 53-high row at 24 px/RU → y = 4 + (53 − 11) × 24 + 5
    dnd('dragOver', r13, 4 + 42 * 24 + 5)
    expect(within(r13).getByTestId('drop-ghost')).toHaveTextContent('✓ Drop here')
    dnd('drop', r13, 4 + 42 * 24 + 5)
    const dlg = screen.getByRole('dialog', { name: 'Confirm move' })
    expect(within(dlg).getByText('Move web-01: R12 RU2 Front → R13 RU10 Front')).toBeInTheDocument()
    await user.click(within(dlg).getByRole('button', { name: 'Move' }))
    expect(await within(dlg).findByRole('alert')).toHaveTextContent('Overlaps db-03 at RU10')
  })

  it('a drop above a 42U cabinet is refused with the reason', async () => {
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    const web = await screen.findByRole('gridcell', { name: WEB })
    const r13 = screen.getByTestId('cabinet-13')
    fireEvent.dragStart(web, { dataTransfer: { setData: () => {}, effectAllowed: '' } })
    dnd('dragOver', r13, 4 + 2 * 24 + 5) // top RU 51
    expect(within(r13).getByTestId('drop-ghost')).toHaveTextContent('✕ exceeds RU42')
    dnd('drop', r13, 4 + 2 * 24 + 5)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('read-only: no drag, no Move/Edit, M does nothing', async () => {
    resetAuth({ role: 'read-only' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    const web = await screen.findByRole('gridcell', { name: WEB })
    expect(web).toHaveAttribute('draggable', 'false')
    await user.click(web)
    const panel = screen.getByRole('complementary', { name: 'Device web-01' })
    expect(within(panel).queryByRole('button', { name: 'Move' })).toBeNull()
    expect(within(panel).queryByRole('button', { name: 'Edit' })).toBeNull()
    act(() => web.focus())
    await user.keyboard('m{ArrowRight}{Enter}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText(/Read-only: moving devices/)).toBeInTheDocument()
  })

  it('rear view reverses the order', async () => {
    renderWithProviders(<App />, '/halls/1/rows/1?face=rear')
    const grid = await screen.findByRole('grid', { name: 'Row cabinets, rear view' })
    expect(within(grid).getAllByRole('row').map((r) => r.getAttribute('aria-label'))).toEqual(['Cabinet R13, 42U', 'Cabinet R12, 53U'])
  })

  it('needs_review device: 1U both faces, Needs profile badge and tooltip, side panel text', async () => {
    db.devices.push({ id: 3, host_name: 'old-01', status: 'active', serial_number: 'X', rack_id: 13, position_u: 10, face: 'rear', device_type_id: null, needs_review: true, needs_review_reason: 'placed_without_profile' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    // Rear-mounted but drawn on the front too (full depth placeholder), 1U
    const cell = await screen.findByRole('gridcell', { name: 'old-01, Active, cabinet R13, RU 10, rear-mounted, pass-through, needs profile' })
    expect(cell.style.height).toBe('24px')
    expect(within(cell).getByTitle('Placed without a profile. Choose a profile.')).toBeInTheDocument()
    await user.click(cell)
    expect(within(screen.getByRole('complementary', { name: 'Device old-01' })).getByText('Placed without a profile. Choose a profile.', { selector: '.hint' })).toBeInTheDocument()
  })

  it('shared profile palette: pick a profile, click a free RU, place with profile_id', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    await screen.findByRole('gridcell', { name: WEB })
    await user.click(screen.getByRole('button', { name: '⇕ Profiles' }))
    await user.click(await within(screen.getByRole('region', { name: 'Profiles' })).findByRole('button', { name: 'Arista 7050X, 1U · Half' }))
    expect(screen.getByRole('status')).toHaveTextContent('Placing Arista 7050X')
    await user.click(screen.getByRole('gridcell', { name: 'Empty, cabinet R13, RU 1 to 42, 42 free' }))
    const dlg = screen.getByRole('dialog', { name: 'Place device' })
    expect(within(dlg).getByRole('group', { name: 'Profile' })).toHaveTextContent('Arista 7050X')
    await user.type(within(dlg).getByLabelText('Hostname'), 'sw-13')
    await user.click(within(dlg).getByRole('button', { name: 'Place device' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({ host_name: 'sw-13', profile_id: 9, device_type_id: 2, rack_id: 13, face: 'front' })
  })

  it('an empty RU without a picked profile opens Choose profile first', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1?zoom=24')
    await user.click(await screen.findByRole('gridcell', { name: 'Empty, cabinet R13, RU 1 to 42, 42 free' }))
    const sheet = screen.getByRole('dialog', { name: 'Choose profile' })
    await user.click(await within(sheet).findByRole('button', { name: 'Dell R650, 2U · Full' }))
    expect(screen.getByRole('dialog', { name: 'Place device' })).toBeInTheDocument()
  })
})
