import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DevicesPage from './DevicesPage'
import { installMockApi, resetAuth, seedDb, type Db } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'

let db: Db
let calls: ReturnType<typeof installMockApi>

beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  db = seedDb()
  calls = installMockApi(db)
})

describe('DevicesPage', () => {
  it('lists devices with serial, rack and type names via lookups', async () => {
    renderWithProviders(<DevicesPage />)
    const row = (await screen.findByText('web-01')).closest('tr')!
    expect(within(row).getByText('SN-A1')).toBeInTheDocument()
    expect(await within(row).findByText('R12')).toBeInTheDocument()
    expect(within(row).getByText('R650')).toBeInTheDocument()
    expect(screen.getByText('1–2 of 2')).toBeInTheDocument()
  })

  it('uses server-side search (host/serial) and status filters', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    await screen.findByText('web-01')
    await user.type(screen.getByLabelText('Search devices'), 'SN-A')
    await waitFor(() => expect(screen.queryByText('db-01')).not.toBeInTheDocument())
    expect(calls.some((c) => c.url.startsWith('/devices?q=SN-A'))).toBe(true)
    await user.clear(screen.getByLabelText('Search devices'))
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'decom')
    await waitFor(() => expect(screen.queryByText('web-01')).not.toBeInTheDocument())
    expect(calls.some((c) => c.url.includes('status=decom'))).toBe(true)
  })

  it('creates a racked device with serial number', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    await screen.findByText('web-01')
    await user.click(screen.getByRole('button', { name: 'Add device' }))
    const form = screen.getByRole('form', { name: 'New device' })
    for (const name of ['Hostname', 'Serial Number']) {
      const el = within(form).getByLabelText(name)
      expect(el).toHaveAttribute('autocapitalize', 'off')
      expect(el).toHaveAttribute('autocorrect', 'off')
      expect(el).toHaveAttribute('autocomplete', 'off')
      expect(el).toHaveAttribute('spellcheck', 'false')
      expect(el).toHaveClass('mono')
    }
    expect(within(form).getByLabelText('Position (RU)')).toHaveAttribute('inputmode', 'numeric')
    await user.type(within(form).getByLabelText('Hostname'), 'sw-01')
    await user.type(within(form).getByLabelText('Serial Number'), 'ASSET-9')
    await within(form).findByRole('option', { name: /7050X/ })
    await user.selectOptions(within(form).getByLabelText('Model'), '2')
    await user.selectOptions(within(form).getByLabelText('Cabinet'), '12')
    await user.type(within(form).getByLabelText('Position (RU)'), '8')
    await user.click(within(form).getByRole('button', { name: 'Rear' }))
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('sw-01')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({
      host_name: 'sw-01', serial_number: 'ASSET-9', device_type_id: 2, rack_id: 12, position_u: 8, face: 'rear', rack: null,
    })
  })

  it('form: only hostname is required; grouped sections, empty groups hidden', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    await screen.findByText('web-01')
    await user.click(await screen.findByRole('button', { name: 'Add device' }))
    const form = screen.getByRole('form', { name: 'New device' })
    expect(within(form).getByText('Basics')).toBeInTheDocument()
    expect(within(form).getByText('Location')).toBeInTheDocument()
    for (const t of ['Power', 'Physical', 'Project']) expect(within(form).queryByText(t)).toBeNull()
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    expect(within(form).getByText('Hostname is required.')).toBeInTheDocument()
    await user.type(within(form).getByLabelText('Hostname'), 'bare-01')
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('bare-01')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({
      host_name: 'bare-01', status: 'install', serial_number: null, device_type_id: null, rack_id: null, position_u: null, rack: null,
    })
  })

  it('optional profile picker loads profiles for the chosen type', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    await screen.findByText('web-01')
    await user.click(await screen.findByRole('button', { name: 'Add device' }))
    const form = screen.getByRole('form', { name: 'New device' })
    expect(within(form).queryByLabelText('Profile')).toBeNull()
    await within(form).findByRole('option', { name: /R650/ })
    await user.selectOptions(within(form).getByLabelText('Model'), '1')
    await user.selectOptions(await within(form).findByLabelText('Profile'), '8')
    await user.type(within(form).getByLabelText('Hostname'), 'gpu-01')
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    await screen.findByText('gpu-01')
    expect(calls.find((c) => c.method === 'POST')!.body).toMatchObject({ device_type_id: 1, profile_id: 8 })
  })

  it('serial not accessible: disables serial, shows note, sends serial null and no unknown fields; table badges empty serial', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    const dbRow = (await screen.findByText('db-01')).closest('tr')!
    expect(within(dbRow).getByText('No serial')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Add device' }))
    const form = screen.getByRole('form', { name: 'New device' })
    await user.type(within(form).getByLabelText('Serial Number'), 'SN-OLD')
    await user.click(within(form).getByLabelText(/Serial not accessible/))
    expect(within(form).getByLabelText('Serial Number')).toBeDisabled()
    await user.type(within(form).getByLabelText('Serial note'), 'behind PSU')
    await user.click(within(form).getByLabelText(/Serial not accessible/))
    expect(within(form).getByLabelText('Serial Number')).toHaveValue('SN-OLD')
    await user.click(within(form).getByLabelText(/Serial not accessible/))
    await user.type(within(form).getByLabelText('Hostname'), 'gpu-07')
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    await screen.findByText('gpu-07')
    const body = calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>
    expect(body.serial_number).toBeNull()
    expect(body).not.toHaveProperty('serial_unavailable')
    expect(body).not.toHaveProperty('serial_note')
  })

  it('shows API 409 detail in the form', async () => {
    installMockApi(db, (m) => (m === 'PATCH' ? new Response(JSON.stringify({ detail: 'Placement U2-U3 overlaps' }), { status: 409 }) : undefined))
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    const row = (await screen.findByText('web-01')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Placement U2-U3 overlaps')
  })

  it('shows structured 409 {code, message} detail (per-cabinet hostname conflict)', async () => {
    installMockApi(db, (m) =>
      m === 'POST'
        ? new Response(JSON.stringify({ detail: { code: 'hostname_conflict', message: "Host name 'web-01' already exists in rack 'R12'" } }), { status: 409 })
        : undefined,
    )
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    await screen.findByText('web-01')
    await user.click(await screen.findByRole('button', { name: 'Add device' }))
    await user.type(screen.getByLabelText('Hostname'), 'web-01')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Host name 'web-01' already exists in rack 'R12'")
  })

  it('Decom from the status control asks first, then PATCHes status and unracks', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    const row = (await screen.findByText('web-01')).closest('tr')!
    expect(within(row).queryByRole('button', { name: 'Delete' })).toBeNull()
    const ctl = within(row).getByRole('radiogroup', { name: 'Status of web-01' })
    await user.click(within(ctl).getByRole('radio', { name: /Decom/ }))
    const dlg = screen.getByRole('dialog', { name: 'Decom web-01?' })
    expect(dlg).toHaveTextContent(/unracked/)
    await user.click(within(dlg).getByRole('button', { name: 'Cancel' }))
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
    await user.click(within(ctl).getByRole('radio', { name: /Decom/ }))
    await user.click(within(screen.getByRole('dialog', { name: 'Decom web-01?' })).getByRole('button', { name: 'Decom' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'decom' }))
    const id = db.devices.find((d) => d.host_name === 'web-01')!
    expect(id).toMatchObject({ status: 'decom', rack_id: null })
    await waitFor(() => expect(within(screen.getByRole('radiogroup', { name: 'Status of web-01' })).getByRole('radio', { name: /Decom/ })).toHaveAttribute('aria-checked', 'true'))
  })

  it('recommissioning a Decom device asks first and sends recommission=true', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DevicesPage />)
    const row = (await screen.findByText('db-01')).closest('tr')!
    await user.click(within(row).getByRole('radio', { name: /Install/ }))
    await user.click(within(screen.getByRole('dialog', { name: 'Recommission db-01?' })).getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'install', recommission: true }))
  })
})
