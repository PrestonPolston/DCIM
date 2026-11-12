import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { jobIntakeApi } from '../api/jobIntake'
import { seedMockJob, seedMockOpenItem } from '../api/jobIntake.mock'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'

function seedRole(role: string = 'admin') {
  resetAuth({ role })
  setCsrfToken('csrf-1')
  installMockApi(seedDb())
}

beforeEach(() => { seedRole('admin') })

async function seedJobWithQueue() {
  const job = seedMockJob({ dcreq: 'DCREQ0004444', name: 'Leaf refresh' })
  seedMockOpenItem({ job_id: job.id, item_type: 'missing_position', hostname: 'leaf-04', target_field: 'position_u', filename: 'epif.csv', import_row_id: 1 })
  seedMockOpenItem({ job_id: job.id, item_type: 'missing_position', hostname: 'leaf-12', target_field: 'position_u', filename: 'epif.csv', import_row_id: 2 })
  seedMockOpenItem({ job_id: job.id, item_type: 'cable_matrix_not_uploaded', import_row_id: 3 })
  return job
}

describe('job detail', () => {
  it('shows the fill-later queue grouped by type', async () => {
    await seedJobWithQueue()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    expect(await screen.findByRole('heading', { name: 'DCREQ0004444' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Leaf refresh · open')
    expect(screen.getByRole('heading', { name: 'Fill-later queue' })).toBeInTheDocument()
    const positions = await screen.findByRole('region', { name: 'missing position' })
    expect(positions).toHaveTextContent('leaf-04')
    expect(positions).toHaveTextContent('leaf-12')
    expect(screen.getByRole('region', { name: 'cable matrix not uploaded' })).toBeInTheDocument()
  })

  it('warns on close when items remain, then closes after acknowledgement and can reopen', async () => {
    await seedJobWithQueue()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    await screen.findByRole('heading', { name: 'DCREQ0004444' })
    await user.click(screen.getByRole('button', { name: 'Close job' }))
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent(/3 unresolved items/)
    expect((await jobIntakeApi().getJob('DCREQ0004444')).status).toBe('open')
    await user.click(within(banner).getByRole('button', { name: 'Close anyway' }))
    expect(await screen.findByRole('button', { name: 'Reopen' })).toBeInTheDocument()
    expect((await jobIntakeApi().getJob('DCREQ0004444')).status).toBe('closed')
    await user.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(await screen.findByRole('button', { name: 'Close job' })).toBeInTheDocument()
    const reopened = await jobIntakeApi().getJob('DCREQ0004444')
    expect(reopened.status).toBe('open')
    expect(reopened.opened_at).toBeTruthy()
  })

  it('lets a read-only user complete an item and hides close', async () => {
    seedRole('read-only')
    await seedJobWithQueue()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    await screen.findByRole('heading', { name: 'Fill-later queue' })
    expect(screen.queryByRole('button', { name: 'Close job' })).toBeNull()
    const positions = await screen.findByRole('region', { name: 'missing position' })
    await user.click(within(positions).getAllByRole('button', { name: 'Complete' })[0])
    await user.click(screen.getByRole('tab', { name: 'Resolved' }))
    expect(await screen.findByRole('region', { name: 'missing position' })).toHaveTextContent('leaf-04')
    expect(await jobIntakeApi().listOpenItems((await jobIntakeApi().getJob('DCREQ0004444')).id, 'resolved')).toMatchObject({
      total: 1,
    })
  })
})
