import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'

beforeEach(() => {
  resetAuth()
  setCsrfToken('csrf-1')
  installMockApi(seedDb())
})

describe('phone shell', () => {
  it('☰ drawer carries the main nav so the top bar can collapse on phones', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1')
    expect(screen.queryByRole('navigation', { name: 'Main (phone)' })).toBeNull()
    await user.click(await screen.findByRole('button', { name: 'Toggle navigation tree' }))
    const nav = screen.getByRole('navigation', { name: 'Main (phone)' })
    expect(within(nav).getByRole('link', { name: 'Devices' })).toHaveAttribute('href', '/devices')
    expect(within(nav).getByRole('button', { name: 'Log out' })).toBeInTheDocument()
    await user.click(within(nav).getByRole('link', { name: 'Reports' }))
    expect(screen.queryByRole('navigation', { name: 'Main (phone)' })).toBeNull()
  })

  it('cabinet: phone hint + palette in a phone-hidden wrapper; tapping an empty RU opens Choose profile (no drag)', async () => {
    const user = userEvent.setup()
    const { container } = renderWithProviders(<App />, '/halls/1/cabinets/12')
    await screen.findByRole('heading', { name: 'Cabinet R12' })
    expect(screen.getByText('Tap an empty RU to add a device from a profile.')).toHaveClass('tap-hint')
    expect(container.querySelector('.palette-profiles')).not.toBeNull()
    await user.click(screen.getByTestId('slot-front-1'))
    expect(screen.getByRole('dialog', { name: 'Choose profile' })).toBeInTheDocument()
  })
})
