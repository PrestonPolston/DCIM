import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../App'
import { installMockApi, resetAuth, seedDb } from '../../test/mockApi'
import { setCsrfToken } from '../../api/client'
import { renderWithProviders } from '../../test/render'

const end = (device_id: number, host_name: string, port_name: string, status = 'active') => ({
  device_id, host_name, status, rack_id: 12, cabinet: 'R12', hall_id: 1, hall: 'Hall 1', row: 'Row 3',
  position_u: 2, face: 'front', port_id: device_id * 10, port_name, slot: null,
})
const conn = { id: 7, a: end(1, 'web-01', 'eth0'), b: end(3, 'sw-01', 'Eth1/1', 'install'), cable: { id: 1, cable_type: 'RJ45', label: 'P-0412', color: 'blue', length_m: '5.00' }, derived_status: 'install', notes: null, created_at: '' }

let calls: ReturnType<typeof installMockApi>
beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  calls = installMockApi(seedDb(), (method, path) => {
    if (method === 'GET' && path === '/connections')
      return new Response(JSON.stringify([conn]), { status: 200, headers: { 'Content-Type': 'application/json', 'X-Total-Count': '46' } })
    return undefined
  })
})

describe('Connections report', () => {
  it('reads GET /connections (count from X-Total-Count), with filters', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/reports')
    const card = (await screen.findByText('Connections')).closest('.card') as HTMLElement
    expect(await within(card).findByText('46 connections')).toBeInTheDocument()
    expect(card).not.toHaveTextContent(/Not available/)
    await user.click(within(card).getByRole('button', { name: 'View →' }))
    const table = await screen.findByRole('table', { name: 'Connections' })
    const row = within(table).getByText('web-01').closest('tr')!
    expect(row).toHaveTextContent('eth0')
    expect(row).toHaveTextContent('sw-01')
    expect(row).toHaveTextContent('P-0412 · RJ45 · blue · 5 m')
    expect(within(row).getByText('Install')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Cable type'), 'LC')
    await waitFor(() => expect(calls.some((c) => c.url.startsWith('/connections?') && c.url.includes('cable_type=LC'))).toBe(true))
  })
})
