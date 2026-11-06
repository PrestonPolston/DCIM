import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { setCsrfToken } from '../api/client'
import { installMockApi, resetAuth, seedDb, type Db } from '../test/mockApi'
import { renderWithProviders } from '../test/render'
import { filterEmptyColumn, parseCsv } from '../lib/csv'

let db: Db
let calls: ReturnType<typeof installMockApi>
beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  db = seedDb()
  calls = installMockApi(db)
})

describe('Reports', () => {
  it('shows cards, Connections card, and the missing-serial preset', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/reports')
    const table = await screen.findByRole('table', { name: 'Devices report' })
    expect(await within(table).findByText('web-01')).toBeInTheDocument()
    expect(screen.queryByText(/Not available yet/)).toBeNull()
    expect(await screen.findByRole('combobox', { name: 'Profile' })).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Device type' })).toBeNull()
    expect(await within(table).findByText(/R12 \/ RU2–3 \/ F/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '⚑ Missing serial' }))
    await waitFor(() => expect(within(table).queryByText('web-01')).toBeNull())
    expect(within(table).getByText('db-01')).toBeInTheDocument()
    expect(within(table).getByText('No serial')).toBeInTheDocument()
  })

  it('passes filters to the API and exports CSV via /devices/export', async () => {
    const created: Blob[] = []
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), 'blob:x'), revokeObjectURL: () => {} }))
    const user = userEvent.setup()
    renderWithProviders(<App />, '/reports')
    await screen.findByRole('table', { name: 'Devices report' })
    await user.selectOptions(screen.getByLabelText('Status'), 'decom')
    await waitFor(() => expect(calls.some((c) => c.url.startsWith('/devices?status=decom'))).toBe(true))
    await user.selectOptions(screen.getByLabelText('Status'), '')
    await user.selectOptions(screen.getByLabelText('Serial'), 'none')
    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    await waitFor(() => expect(created).toHaveLength(1))
    expect(calls.some((c) => c.url.startsWith('/devices/export'))).toBe(true)
    const rows = parseCsv(await created[0].text())
    expect(rows.slice(1).map((r) => r[1])).toEqual(['db-01'])
  })
})

describe('csv', () => {
  it('filters rows with an empty column, keeping quoted fields', () => {
    const out = filterEmptyColumn('id,host_name,serial_number\r\n1,"a,b",SN\r\n2,"x ""y""",\r\n', 'serial_number')
    expect(parseCsv(out)).toEqual([['id', 'host_name', 'serial_number'], ['2', 'x "y"', '']])
  })

  it('Needs review preset sends needs_review=true and shows the badge', async () => {
    db.devices.push({ id: 3, host_name: 'old-01', status: 'active', serial_number: 'X', rack_id: 12, position_u: 10, face: 'front', device_type_id: null, needs_review: true, needs_review_reason: 'profile_not_published' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/reports')
    const table = await screen.findByRole('table', { name: 'Devices report' })
    await user.click(screen.getByRole('button', { name: '? Needs review' }))
    await waitFor(() => expect(within(table).queryByText('web-01')).toBeNull())
    expect(within(table).getByText('old-01')).toBeInTheDocument()
    expect(within(table).getByTitle("Its profile isn't published yet. Publish the profile or choose another.")).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'GET' && c.url.includes('needs_review=true'))).toBe(true)
  })
})
