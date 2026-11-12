import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { jobIntakeApi } from '../api/jobIntake'
import { seedMockJob } from '../api/jobIntake.mock'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'

function seedRole(role: string = 'admin') {
  resetAuth({ role })
  setCsrfToken('csrf-1')
  installMockApi(seedDb())
}

function csv(name: string, body: string) {
  return new File([body], name, { type: 'text/csv' })
}

const EPIF = `hostname,result
srv-ready,ready
srv-warn,warning
CONFLICT-01,conflict
`

beforeEach(() => { seedRole('admin') })
afterEach(() => {})

describe('New job entry points', () => {
  it('lets admin and technician open the wizard from Home', async () => {
    renderWithProviders(<App />, '/')
    expect(await screen.findByRole('link', { name: 'New job' })).toHaveAttribute('href', '/jobs/new')
  })

  it('lets a technician open the wizard from Import', async () => {
    seedRole('technician')
    renderWithProviders(<App />, '/import')
    expect(await screen.findByRole('link', { name: 'New job' })).toHaveAttribute('href', '/jobs/new')
  })

  it('hides New job from read-only users on Home and Import', async () => {
    seedRole('read-only')
    const home = renderWithProviders(<App />, '/')
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'New job' })).toBeNull()
    home.unmount()
    renderWithProviders(<App />, '/import')
    expect(await screen.findByRole('heading', { name: 'CSV import' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'New job' })).toBeNull()
  })
})

describe('DCREQ step', () => {
  it('keeps Next disabled until the DCREQ is valid and shows a format hint', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/new')
    expect(await screen.findByRole('heading', { name: 'New job' })).toBeInTheDocument()
    const next = screen.getByRole('button', { name: 'Next: ePIF' })
    expect(next).toBeDisabled()
    const input = screen.getByLabelText('DCREQ')
    await user.type(input, '12')
    expect(next).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(/DCREQ000 \+ 4 digits/)
    await user.clear(input)
    await user.type(input, '1234')
    expect(next).toBeEnabled()
    expect(screen.getByText('Will be saved as DCREQ0001234.')).toBeInTheDocument()
  })

  it('creates the job and advances to the ePIF step', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/new')
    await screen.findByRole('heading', { name: 'New job' })
    await user.type(screen.getByLabelText('DCREQ'), 'DCREQ0001234')
    await user.click(screen.getByRole('button', { name: 'Next: ePIF' }))
    expect(await screen.findByRole('heading', { name: 'New job · DCREQ0001234' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Space & Power (ePIF)' })).toBeInTheDocument()
    expect(screen.getByLabelText('Job intake steps').querySelector('[aria-current="step"]')).toHaveTextContent('ePIF')
  })

  it('hard-stops a duplicate DCREQ and lets the user start over with a different number', async () => {
    seedMockJob({ dcreq: 'DCREQ0001234', name: 'DCREQ0001234', status: 'open' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/jobs/new')
    await screen.findByRole('heading', { name: 'New job' })
    await user.type(screen.getByLabelText('DCREQ'), '1234')
    await user.click(screen.getByRole('button', { name: 'Next: ePIF' }))
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('DCREQ0001234 is already a job (DCREQ0001234, open)')
    expect(banner).toHaveTextContent("Attaching more work to that job isn’t available yet.")
    expect(within(banner).getByRole('link', { name: 'Open that job' })).toHaveAttribute('href', '/jobs/DCREQ0001234')
    expect(screen.getByRole('button', { name: 'Next: ePIF' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Use a different DCREQ' }))
    expect(screen.queryByText(/already a job/)).toBeNull()
    expect(screen.getByLabelText('DCREQ')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Next: ePIF' })).toBeDisabled()
  })
})

describe('CSV upload, preview and import result', () => {
  async function startJob(user: ReturnType<typeof userEvent.setup>, dcreq = 'DCREQ0002222') {
    renderWithProviders(<App />, '/jobs/new')
    await screen.findByRole('heading', { name: 'New job' })
    await user.type(screen.getByLabelText('DCREQ'), dcreq)
    await user.click(screen.getByRole('button', { name: 'Next: ePIF' }))
    await screen.findByRole('heading', { name: `New job · ${dcreq}` })
  }

  it('blocks a file with a forbidden column and lists the header name, never the secret', async () => {
    const user = userEvent.setup()
    await startJob(user)
    const file = csv('secrets.csv', 'hostname,ilo password\nbox-01,hunter2\n')
    await user.upload(screen.getByLabelText('Space & Power (ePIF) CSV'), file)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/ilo password/i)
    expect(alert).not.toHaveTextContent('hunter2')
    expect(screen.getByRole('button', { name: 'Next: Cable matrix' })).toBeDisabled()
  })

  it('uploads ePIF, skips the cable matrix, and shows warnings, skipped conflicts and fill-later items after commit', async () => {
    const user = userEvent.setup()
    await startJob(user, 'DCREQ0003333')
    await user.upload(screen.getByLabelText('Space & Power (ePIF) CSV'), csv('epif.csv', EPIF))
    expect(await screen.findByRole('status')).toHaveTextContent('epif.csv: 3 rows')
    expect(screen.getByRole('status')).toHaveTextContent('1 ready')
    expect(screen.getByRole('status')).toHaveTextContent('1 warning')
    expect(screen.getByRole('status')).toHaveTextContent('1 conflict')
    await user.click(screen.getByRole('button', { name: 'Next: Cable matrix' }))
    await user.click(screen.getByRole('button', { name: 'Skip cable matrix' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/cable_matrix_not_uploaded/)
    await user.click(screen.getByRole('button', { name: 'Next: Preview' }))
    expect(await screen.findByRole('heading', { name: /Preview/ })).toBeInTheDocument()
    expect(screen.getByText(/ePIF 3 rows/)).toBeInTheDocument()
    expect(screen.getByText(/Cable skipped/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Items that will stay in the fill-later queue/ })).toBeInTheDocument()
    const pending = screen.getByRole('list', { name: 'Pending fill-later items' })
    expect(pending).toHaveTextContent('srv-warn')
    expect(pending).toHaveTextContent('CONFLICT-01')
    expect(pending).toHaveTextContent('cable matrix not uploaded')
    await user.click(screen.getByRole('button', { name: /Commit job/ }))
    const result = await screen.findByRole('region', { name: 'Import result' })
    expect(result).toHaveTextContent('Import result · DCREQ0003333')
    expect(result).toHaveTextContent('No RU.')
    expect(within(result).getByRole('table', { name: 'Skipped conflict rows' })).toHaveTextContent('CONFLICT-01')
    const queue = within(result).getByRole('list', { name: 'Fill-later queue' })
    expect(queue).toHaveTextContent('srv-warn')
    expect(queue).toHaveTextContent('CONFLICT-01')
    expect(queue).toHaveTextContent('cable matrix not uploaded')
    const job = await jobIntakeApi().getJob('DCREQ0003333')
    expect(job.device_count).toBe(2)
    expect(job.unresolved_count).toBe(3)
  })
})
