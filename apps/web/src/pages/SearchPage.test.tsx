import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'
import { loadRecent, pushRecent } from '../lib/recentSearches'

let calls: ReturnType<typeof installMockApi>
beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  localStorage.clear()
  calls = installMockApi(seedDb())
})

describe('Search', () => {
  it('is one tap from home and searches host name or serial with a trimmed q', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1')
    await user.click(await screen.findByRole('link', { name: 'Search devices by host name or serial' }))
    const box = screen.getByRole('searchbox', { name: 'Search host name or serial' })
    expect(box).toHaveFocus()
    expect(box).toHaveAttribute('autocapitalize', 'off')
    await user.type(box, '  SN-A ')
    const card = await screen.findByRole('link', { name: /web-01/ })
    expect(calls.some((c) => c.url.startsWith('/devices?q=SN-A&'))).toBe(true)
    expect(calls.some((c) => /q=%20|q=\+/.test(c.url))).toBe(false)
    expect(card).toHaveAttribute('href', '/cabinets/12?device=1')
    expect(within(card).getByText('SN SN-A1')).toBeInTheDocument()
    await user.click(card)
    expect(loadRecent()).toEqual(['SN-A'])
  })

  it('shows the No serial empty state and recents; one char does not search', async () => {
    pushRecent('web-0')
    const user = userEvent.setup()
    renderWithProviders(<App />, '/search')
    const box = await screen.findByRole('searchbox', { name: 'Search host name or serial' })
    expect(screen.getByRole('button', { name: 'web-0' })).toBeInTheDocument()
    await user.type(box, 'z')
    expect(screen.getByText('Type at least 2 characters.')).toBeInTheDocument()
    await user.type(box, 'zz-nothing')
    expect(await screen.findByRole('status')).toHaveTextContent('No match. Devices without a serial can only be found by host name.')
    await user.click(screen.getByRole('button', { name: 'Clear search' }))
    await user.click(await screen.findByRole('button', { name: 'web-0' }))
    await waitFor(() => expect(screen.getByRole('link', { name: /web-01/ })).toBeInTheDocument())
  })

  it('a device without a serial shows the No serial badge', async () => {
    renderWithProviders(<App />, '/search?q=db-01')
    const card = await screen.findByRole('link', { name: /db-01/ })
    expect(within(card).getByText('No serial')).toBeInTheDocument()
    expect(within(card).getByText('Not in a cabinet')).toBeInTheDocument()
  })
})
