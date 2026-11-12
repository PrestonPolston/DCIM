import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { seedMockJob, seedMockOpenItem } from '../api/jobIntake.mock'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'

function seedRole(role: string = 'admin') {
  resetAuth({ role })
  setCsrfToken('csrf-1')
  installMockApi(seedDb())
}

const ago = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString()

beforeEach(() => { seedRole('admin') })

describe('jobs list', () => {
  it('is linked from the main nav and lists status, open-item counts, and the overdue flag', async () => {
    const current = seedMockJob({ dcreq: 'DCREQ0001111', name: 'Leaf refresh' })
    seedMockOpenItem({ job_id: current.id, item_type: 'missing_position', hostname: 'leaf-04' })
    seedMockOpenItem({ job_id: current.id, item_type: 'cable_matrix_not_uploaded' })
    seedMockJob({ dcreq: 'DCREQ0002222', name: 'Old spine', opened_at: ago(40) })

    renderWithProviders(<App />, '/')
    expect(await screen.findByRole('link', { name: 'Jobs' })).toHaveAttribute('href', '/jobs')
    await userEvent.setup().click(screen.getAllByRole('link', { name: 'Jobs' })[0])

    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Jobs' })
    const leaf = within(table).getByRole('row', { name: /DCREQ0001111/ })
    expect(leaf).toHaveTextContent('Leaf refresh')
    expect(leaf).toHaveTextContent('open')
    expect(leaf).toHaveTextContent('2')
    expect(within(leaf).getByRole('link', { name: 'DCREQ0001111' })).toHaveAttribute('href', '/jobs/DCREQ0001111')
    expect(leaf).not.toHaveTextContent('Open more than 30 days')

    const old = within(table).getByRole('row', { name: /DCREQ0002222/ })
    expect(old).toHaveTextContent('Open more than 30 days')
    expect(old).toHaveTextContent('0')
  })

  it('filters to jobs open more than 30 days', async () => {
    seedMockJob({ dcreq: 'DCREQ0001111' })
    seedMockJob({ dcreq: 'DCREQ0002222', opened_at: ago(40) })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs')
    await screen.findByRole('table', { name: 'Jobs' })
    await user.selectOptions(screen.getByLabelText('Age'), 'true')
    const table = await screen.findByRole('table', { name: 'Jobs' })
    expect(within(table).getByRole('link', { name: 'DCREQ0002222' })).toBeInTheDocument()
    expect(within(table).queryByRole('link', { name: 'DCREQ0001111' })).toBeNull()
  })

  it('lets a read-only user open the list but hides New job', async () => {
    seedRole('read-only')
    seedMockJob({ dcreq: 'DCREQ0001111' })
    renderWithProviders(<App />, '/jobs')
    expect(await screen.findByRole('table', { name: 'Jobs' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'New job' })).toBeNull()
  })
})
