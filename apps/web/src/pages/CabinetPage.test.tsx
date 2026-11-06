import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
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

describe('cabinet device detail', () => {
  it('opens from the ?device= deep link', async () => {
    renderWithProviders(<App />, '/cabinets/12?device=1')
    const panel = await screen.findByRole('complementary', { name: 'Device web-01' })
    expect(within(panel).getByRole('radiogroup', { name: 'Status of web-01' })).toBeInTheDocument()
    expect(within(panel).getByText('SN-A1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /web-01, Active/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('opens and closes when the device is tapped in the elevation', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/cabinets/12')
    const block = await screen.findByRole('button', { name: /web-01, Active/ })
    expect(screen.queryByRole('complementary', { name: 'Device web-01' })).toBeNull()
    await user.click(block)
    const panel = screen.getByRole('complementary', { name: 'Device web-01' })
    await user.click(within(panel).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Device web-01' })).toBeNull())
    await user.click(block)
    await user.click(within(screen.getByRole('complementary', { name: 'Device web-01' })).getByRole('button', { name: 'Edit' }))
    expect(await screen.findByRole('form', { name: 'Edit device' })).toBeInTheDocument()
  })

  it('draws the profile front (DeviceFront art) behind the readable label', async () => {
    renderWithProviders(<App />, '/cabinets/12')
    const block = await screen.findByRole('button', { name: /web-01, Active/ })
    expect(block).toHaveClass('has-art')
    expect(block.querySelector('.u-device-art .df')).not.toBeNull()
    expect(within(block).getByText('web-01')).toBeInTheDocument()
  })

  it('palette has no Unknown asset-type chip (no typeless concept)', async () => {
    renderWithProviders(<App />, '/cabinets/12')
    const pal = await screen.findByRole('complementary', { name: 'Device palette' })
    expect(within(pal).queryByRole('button', { name: 'Unknown' })).toBeNull()
    expect(within(pal).getByRole('button', { name: 'Router' })).toBeInTheDocument()
  })
})
