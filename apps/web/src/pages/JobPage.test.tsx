import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
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
    const positions = await screen.findByRole('region', { name: 'Missing position' })
    expect(positions).toHaveTextContent('leaf-04')
    expect(positions).toHaveTextContent('leaf-12')
    expect(screen.getByRole('region', { name: 'Cable matrix not uploaded' })).toBeInTheDocument()
  })

  it('warns on close when items remain, then closes after acknowledgement and can reopen', async () => {
    await seedJobWithQueue()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    await screen.findByRole('heading', { name: 'DCREQ0004444' })
    await user.click(screen.getByRole('button', { name: 'Close job' }))
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('This job still has 3 unresolved items. You can close it anyway.')
    expect(banner).not.toHaveTextContent('acknowledge_open_items')
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

  it('lets a read-only user view the queue but hides close and item actions', async () => {
    seedRole('read-only')
    await seedJobWithQueue()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    await screen.findByRole('heading', { name: 'Fill-later queue' })
    expect(await screen.findByRole('region', { name: 'Missing position' })).toHaveTextContent('leaf-04')
    expect(screen.queryByRole('button', { name: 'Close job' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Fill' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Hold' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull()
  })

  it('Fill writes the field then resolves, and the header count stays consistent on every tab', async () => {
    await seedJobWithQueue()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    await screen.findByRole('heading', { name: 'Fill-later queue' })
    expect(screen.getByTestId('job-queue-summary')).toHaveTextContent('3 in the fill-later queue')
    const positions = await screen.findByRole('region', { name: 'Missing position' })
    await user.click(within(positions).getAllByRole('button', { name: 'Fill' })[0])
    await user.type(screen.getByLabelText('Value for position_u'), '42')
    await user.click(screen.getByRole('button', { name: 'Save and resolve' }))
    await waitFor(() => {
      expect(screen.getByTestId('job-queue-summary')).toHaveTextContent('2 in the fill-later queue')
    })
    await user.click(screen.getByRole('tab', { name: /^Resolved$/ }))
    expect(await screen.findByRole('region', { name: 'Missing position' })).toHaveTextContent('leaf-04')
    expect(screen.getByText(/position \(U\) set to 42/)).toBeInTheDocument()
    expect(screen.getByTestId('job-queue-summary')).toHaveTextContent('2 in the fill-later queue')
    const job = await jobIntakeApi().getJob('DCREQ0004444')
    expect(job.unresolved_count).toBe(2)
    const resolved = await jobIntakeApi().listOpenItems(job.id, 'resolved')
    expect(resolved.items[0]).toMatchObject({ filled_value: '42', status: 'resolved' })
  })


  it('tells you Complete does not write a tied field, and mock Fill still writes the value', async () => {
    await seedJobWithQueue()
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/DCREQ0004444')
    const positions = await screen.findByRole('region', { name: 'Missing position' })
    expect(within(positions).getAllByRole('note')[0]).toHaveTextContent("Complete marks this resolved. It doesn't write position (U).")
    expect(screen.getByRole('region', { name: 'Cable matrix not uploaded' }).querySelector('[role="note"]')).toBeNull()
    expect(within(positions).getAllByRole('button', { name: 'Fill' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Resolve with note' })).toBeNull()
    await user.click(within(positions).getAllByRole('button', { name: 'Fill' })[0])
    expect(screen.getByLabelText('Value for position_u')).toBeInTheDocument()
    expect(screen.queryByLabelText('Note')).toBeNull()
  })

  it('keeps line breaks in item notes and pluralizes 1 device', async () => {
    const job = seedMockJob({ dcreq: 'DCREQ0005555', name: 'One device', device_count: 1, connection_count: 1 })
    seedMockOpenItem({
      job_id: job.id,
      item_type: 'pdu_missing',
      hostname: 'web11',
      note: 'Held over.\nCheck PDU 2.',
      filename: 'epif.csv',
      import_row_id: 1,
    })
    renderWithProviders(<App />, '/jobs/DCREQ0005555')
    await screen.findByRole('heading', { name: 'DCREQ0005555' })
    expect(await screen.findByRole('region', { name: 'Missing PDU' })).toHaveTextContent('web11')
    expect(screen.getByTestId('job-queue-summary').textContent).toMatch(/1 device · 1 connection/)
    expect(screen.getByTestId('job-queue-summary').textContent).not.toMatch(/1 devices/)
    expect(screen.getByTestId('job-queue-summary').textContent).not.toMatch(/1 connections/)
    const note = document.querySelector('.job-item-note')
    expect(note).toBeTruthy()
    expect(note?.textContent).toBe('Held over.\nCheck PDU 2.')
    expect(note).toHaveClass('job-item-note')
  })


  it('shows cable label and trail on cable-matrix queue items', async () => {
    const job = seedMockJob({ dcreq: 'DCREQ0006666', name: 'Cables', connection_count: 1 })
    seedMockOpenItem({
      job_id: job.id,
      item_type: 'unresolved_hop',
      hostname: 'sw1',
      cable_label: 'CAB-6',
      cable_trail: 'T-1',
      target_field: 'hop_1',
      filename: 'cables.csv',
      source: 'cable_matrix',
      import_row_id: 1,
    })
    renderWithProviders(<App />, '/jobs/DCREQ0006666')
    const hops = await screen.findByRole('region', { name: 'Unresolved hop' })
    expect(hops).toHaveTextContent('sw1')
    expect(hops).toHaveTextContent('CAB-6')
    expect(hops).toHaveTextContent('T-1')
    expect(hops).toHaveTextContent('hop 1')
    expect(screen.getByTestId('job-queue-summary').textContent).toMatch(/1 connection/)
  })
})
