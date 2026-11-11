import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { DeviceIssuesTile, ParkedCard, ProfileHealthTile, Tile } from '../components/home/HomeTiles'
import { PARKED, type ProfileHealth } from '../api/home'
import { fixtureDeviceIssues, fixtureProfileHealth, PROFILE_FIXTURES } from '../api/home.mock'
import { installMockApi, PROFILES, resetAuth, seedDb, type Db } from '../test/mockApi'
import { setCsrfToken } from '../api/client'
import { renderWithProviders } from '../test/render'

const ORIGIN = PROFILES.map((p) => ({ ...p }))
const NOW_HEALTH = fixtureProfileHealth()

function seedHome(role: string = 'admin'): Db {
  resetAuth({ role })
  setCsrfToken('csrf-1')
  const db = seedDb()
  db.devices.push({ id: 10, host_name: 'spare-01', status: 'install', serial_number: null, rack_id: null, position_u: null, face: 'front', device_type_id: 1 })
  PROFILES.length = 0
  PROFILES.push(...(PROFILE_FIXTURES as typeof PROFILES))
  installMockApi(db)
  return db
}

beforeEach(() => { seedHome('admin') })
afterEach(() => { PROFILES.length = 0; PROFILES.push(...ORIGIN) })

describe('routing of / and the hall', () => {
  it('renders the home page at / and does not redirect to the hall', async () => {
    renderWithProviders(<App />, '/')
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
    expect(await screen.findByRole('link', { name: 'Hall' })).toHaveAttribute('href', '/halls/1')
    expect(screen.queryByLabelText('Center aisle')).toBeNull()
  })

  it('keeps the hall view at /halls/:id', async () => {
    renderWithProviders(<App />, '/halls/1')
    expect(await screen.findByRole('link', { name: /Cabinet R12/ })).toHaveAttribute('href', '/halls/1/cabinets/12')
    expect(screen.getByLabelText('Center aisle')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Home' })).toBeNull()
  })
})

describe('role gating of My work | Admin', () => {
  it('admins see the switch, default to My work, and can open Admin via the control or ?view=admin', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/')
    const tabs = await screen.findByRole('tablist', { name: 'Home view' })
    expect(within(tabs).getByRole('tab', { name: 'My work' })).toHaveAttribute('aria-selected', 'true')
    expect(within(tabs).getByRole('tab', { name: 'Admin' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByText('Current jobs')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Profile health/ })).toBeNull()
    await user.click(within(tabs).getByRole('tab', { name: 'Admin' }))
    expect(await screen.findByRole('heading', { name: /Profile health/ })).toBeInTheDocument()
    expect(within(screen.getByRole('tablist', { name: 'Home view' })).getByRole('tab', { name: 'Admin' })).toHaveAttribute('aria-selected', 'true')
  })

  it('opens the Admin view from ?view=admin', async () => {
    renderWithProviders(<App />, '/?view=admin')
    expect(await screen.findByRole('heading', { name: /Profile health/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Device issues' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Workload' })).toBeInTheDocument()
  })

  it('technicians never see the Admin switch or tiles, even with ?view=admin', async () => {
    seedHome('technician')
    renderWithProviders(<App />, '/?view=admin')
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('tablist', { name: 'Home view' })).toBeNull()
    expect(screen.getByText('Current jobs')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Profile health/ })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Workload' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Add profile' })).toBeInTheDocument()
  })

  it('read-only users never see Admin and have no add-profile action', async () => {
    seedHome('read-only')
    renderWithProviders(<App />, '/?view=admin')
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('tablist', { name: 'Home view' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Add profile' })).toBeNull()
    expect(screen.queryByRole('heading', { name: /Profile health/ })).toBeNull()
  })
})

describe('parked cards', () => {
  it('shows the not-available state on My work job tiles and on Admin power / workload', async () => {
    renderWithProviders(<App />, '/')
    expect(await screen.findByText('Current jobs')).toBeInTheDocument()
    expect(screen.getAllByText(/Not available yet/).length).toBeGreaterThanOrEqual(4)
    expect(screen.getAllByText('Needs jobs/DCREQ logic (parked)').length).toBeGreaterThanOrEqual(4)
    expect(screen.getAllByText(/Needs jobs\/DCREQ logic\./).length).toBeGreaterThanOrEqual(1)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Admin' }))
    expect(await screen.findByTestId('power-parked')).toHaveTextContent('Needs power assignment — —')
    expect(screen.getByTestId('power-parked')).toHaveTextContent('Needs device_psu_assignments')
    expect(screen.getByText('Workload')).toBeInTheDocument()
    expect(screen.getByText('Audit log (later)')).toBeInTheDocument()
  })
})

describe('profile health and device issues', () => {
  it('lists needs-review, stale drafts and recently retired, plus unplaced devices, and uses official filters', async () => {
    renderWithProviders(<App />, '/?view=admin')
    expect(await screen.findByText('Generic 1U server · Default')).toBeInTheDocument()
    expect(screen.getByText(/Needs rear image/)).toBeInTheDocument()
    expect(screen.getByText('Acme X100 · Default')).toBeInTheDocument()
    expect(screen.getByText('Acme Racks 42U · Old')).toBeInTheDocument()
    expect(screen.getByText('spare-01')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All 1 unplaced' })).toHaveAttribute('href', '/devices?status=install&status=active&unplaced=true')
    expect(screen.getByRole('link', { name: 'Profiles worklist' })).toHaveAttribute('href', '/profiles?status=published&usable=false')
  })

  it('shows empty copy when there is nothing to review and every live device is placed', async () => {
    PROFILES.length = 0
    PROFILES.push({ id: 7, device_type_id: 1, name: 'R650 default', is_default: true, u_height: 2, is_full_depth: true, status: 'published', usable: true } as (typeof PROFILES)[0])
    installMockApi(seedDb())
    renderWithProviders(<App />, '/?view=admin')
    expect(await screen.findByText('Profiles look healthy.')).toBeInTheDocument()
    expect(screen.getByText('All live devices have a position.')).toBeInTheDocument()
  })

  it('shows a per-tile error with Retry when the summary request fails', async () => {
    installMockApi(seedDb(), (method, path) =>
      method === 'GET' && path === '/profiles' ? new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }) : undefined)
    renderWithProviders(<App />, '/?view=admin')
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.some((el) => /Couldn’t load profile health/.test(el.textContent ?? ''))).toBe(true)
    expect(screen.getAllByRole('button', { name: 'Retry' }).length).toBeGreaterThanOrEqual(1)
  })
})

describe('quick search', () => {
  it('finds a device, cabinet, row and hall, and parks DCREQ search', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/')
    const box = await screen.findByRole('searchbox', { name: 'Search device, cabinet, row or hall' })
    await user.type(box, 'R12')
    const panel = await screen.findByRole('listbox', { name: 'Search results' })
    expect(await within(panel).findByRole('option', { name: /R12/ })).toHaveAttribute('href', '/cabinets/12')
    await user.clear(box)
    await user.type(box, 'web-01')
    expect(await within(await screen.findByRole('listbox')).findByRole('option', { name: /web-01/ })).toHaveAttribute('href', '/cabinets/12?device=1')
    await user.clear(box)
    await user.type(box, 'Row')
    expect(await within(await screen.findByRole('listbox')).findByRole('option', { name: /Row 3/ })).toHaveAttribute('href', '/halls/1/rows/1')
    await user.clear(box)
    await user.type(box, 'Hall')
    expect(await within(await screen.findByRole('listbox')).findByRole('option', { name: /Hall 2/ })).toHaveAttribute('href', '/halls/1')
    expect(screen.getByTestId('dcreq-search-parked')).toHaveTextContent('Not available yet. DCREQ search is not available yet.')
  })

  it('hints instead of searching when the query is under 2 characters', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/')
    const box = await screen.findByRole('searchbox', { name: 'Search device, cabinet, row or hall' })
    await user.type(box, 'w')
    expect(await screen.findByText('Type at least 2 characters.')).toBeInTheDocument()
    expect(screen.queryByText('Searching…')).toBeNull()
    expect(screen.queryByTestId('dcreq-search-parked')).toBeNull()
  })

  it('shows Show all N when a group is truncated and expands on click', async () => {
    const user = userEvent.setup()
    const db = seedHome('admin')
    for (let i = 0; i < 6; i++) db.racks.push({ id: 100 + i, row_id: 1, name: `Cab-${i}`, u_height: 42 })
    installMockApi(db)
    renderWithProviders(<App />, '/')
    const box = await screen.findByRole('searchbox', { name: 'Search device, cabinet, row or hall' })
    await user.type(box, 'Cab')
    const panel = await screen.findByRole('listbox', { name: 'Search results' })
    expect(await within(panel).findByRole('button', { name: 'Show all 6' })).toBeInTheDocument()
    expect(within(panel).getAllByRole('option').filter((el) => /Cab-/.test(el.textContent ?? ''))).toHaveLength(5)
    await user.click(within(panel).getByRole('button', { name: 'Show all 6' }))
    expect(await within(panel).findByRole('option', { name: /Cab-5/ })).toBeInTheDocument()
    expect(within(panel).getAllByRole('option').filter((el) => /Cab-/.test(el.textContent ?? ''))).toHaveLength(6)
    expect(within(panel).queryByRole('button', { name: 'Show all 6' })).toBeNull()
  })

  it('labels an unplaced device as No position', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/')
    const box = await screen.findByRole('searchbox', { name: 'Search device, cabinet, row or hall' })
    await user.type(box, 'spare-01')
    const opt = await within(await screen.findByRole('listbox')).findByRole('option', { name: /spare-01/ })
    expect(opt).toHaveAttribute('href', '/devices?q=spare-01')
    expect(opt).toHaveTextContent('No position')
  })

  it('focuses the header search when / is pressed', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/')
    await screen.findByRole('heading', { name: 'Home' })
    await user.keyboard('/')
    expect(screen.getByRole('searchbox', { name: 'Search device, cabinet, row or hall' })).toHaveFocus()
  })
})

describe('tile loading, empty and error states (presentational)', () => {
  it('renders a skeleton, an empty line, an error with retry, and a parked card', async () => {
    const { rerender } = renderWithProviders(<Tile title="Current jobs" loading />, '/')
    expect(screen.getByLabelText('Loading Current jobs')).toBeInTheDocument()
    rerender(<Tile title="Current jobs" empty="No open jobs." />)
    expect(screen.getByText('No open jobs.')).toBeInTheDocument()
    const retry = { called: false }
    rerender(<Tile title="Current jobs" error="nope" onRetry={() => { retry.called = true }} />)
    expect(screen.getByRole('alert')).toHaveTextContent(/Couldn’t load current jobs/)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry.called).toBe(true)
    rerender(<ParkedCard title="Current jobs" tile={PARKED.jobs} />)
    expect(screen.getByText(/Not available yet/)).toBeInTheDocument()
    expect(screen.getByText('Needs jobs/DCREQ logic (parked)')).toBeInTheDocument()
  })

  it('renders profile health and device-issue empty states from fixtures', () => {
    const emptyHealth: ProfileHealth = {
      ...NOW_HEALTH,
      needs_review: { ...NOW_HEALTH.needs_review, count: 0, items: [], by_issue: { rear_image_missing: 0, orientation_missing: 0 } },
      stale_drafts: { ...NOW_HEALTH.stale_drafts, count: 0, items: [] },
      recently_retired: { ...NOW_HEALTH.recently_retired, count: 0, items: [] },
    }
    renderWithProviders(<ProfileHealthTile data={emptyHealth} canFix />, '/')
    expect(screen.getByText('Profiles look healthy.')).toBeInTheDocument()
    cleanup()
    renderWithProviders(<DeviceIssuesTile data={fixtureDeviceIssues()} canPlace />, '/')
    expect(screen.getByText('r01c03-srv-09')).toBeInTheDocument()
    cleanup()
    renderWithProviders(<DeviceIssuesTile data={{ ...fixtureDeviceIssues(), no_position: { count: 0, truncated: false, items: [], filter: 'status=install&status=active&unplaced=true' } }} canPlace />, '/')
    expect(screen.getByText('All live devices have a position.')).toBeInTheDocument()
  })

  it('truncates a long no-position hostname with a hover title', () => {
    const hostname = 'very-long-unplaced-device-hostname-that-should-not-overflow-the-device-issues-tile'
    const issues = fixtureDeviceIssues()
    renderWithProviders(
      <DeviceIssuesTile
        data={{
          ...issues,
          no_position: {
            ...issues.no_position,
            count: 1,
            truncated: false,
            items: [{ id: 99, hostname, status: 'install', updated_at: '2026-11-11T14:00:00Z' }],
          },
        }}
        canPlace
      />,
      '/',
    )
    const host = screen.getByText(hostname)
    expect(host).toHaveClass('home-host')
    expect(host).toHaveAttribute('title', hostname)
  })
})
