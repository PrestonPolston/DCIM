import { beforeEach, describe, expect, it, vi } from 'vitest'
import { forwardRef, useImperativeHandle } from 'react'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { setCsrfToken } from '../api/client'
import { installMockApi, resetAuth, seedDb } from '../test/mockApi'
import { renderWithProviders } from '../test/render'

// jsdom has no WebGL: pretend it does and replace the lazy three.js chunk with a stub
// that exposes its props, so the page shell (toolbar, cards, list, keyboard) is testable.
const h = vi.hoisted(() => ({ props: null as null | Record<string, unknown>, calls: [] as string[], webgl: true }))
vi.mock('../lib/webgl', async (orig) => ({ ...(await orig<typeof import('../lib/webgl')>()), hasWebGL: () => h.webgl, prefersReducedMotion: () => false }))
vi.mock('../components/row3d/Row3DView', () => ({
  default: forwardRef(function Stub(props: Record<string, unknown>, ref) {
    h.props = props
    useImperativeHandle(ref, () => ({
      flip: () => h.calls.push('flip'),
      setSide: (s: string) => h.calls.push(`side:${s}`),
      preset: (k: string) => h.calls.push(`preset:${k}`),
      focusCabinet: (i: number) => h.calls.push(`focus:${i}`),
      zoom: (f: number) => h.calls.push(`zoom:${f}`),
      stats: () => null,
    }))
    return <div data-testid="r3d-stub" />
  }),
}))

beforeEach(() => {
  resetAuth(); setCsrfToken('csrf-1'); localStorage.clear()
  installMockApi(seedDb())
  h.props = null; h.calls = []; h.webgl = true
})

const props = () => h.props as unknown as {
  onPick: (id: number | null) => void; onHover: (id: number | null, x: number, y: number) => void
  onView: (s: 'front' | 'rear') => void; onFatal: (e: Error) => void
  selectedId: number | null; highlight: string; tag: { id: number; text: string } | null; cabinetLabels: boolean; rowName?: string
  scene: { cabinets: { name: string }[]; boxes: unknown[] }
}

describe('3D row view (default)', () => {
  it('is the default row view, lazy-loads the canvas and builds the scene from the row data', async () => {
    renderWithProviders(<App />, '/halls/1/rows/1')
    await screen.findByTestId('r3d-stub')
    expect(screen.getByRole('toolbar', { name: '3D row view' })).toBeInTheDocument()
    expect(props().scene.cabinets.map((c) => c.name)).toEqual(['R12', 'R13'])
    expect(props().scene.boxes.length).toBeGreaterThan(0)
    expect(screen.getByText('Front (aisle)')).toBeInTheDocument()
    expect(screen.getByText(/Highlighting: None/)).toBeInTheDocument()
    expect(props().tag).toBeNull() // nothing selected: no device names at all
    expect(props().rowName).toBe('Row 3')
    const toggle = screen.getByRole('button', { name: 'Labels' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveAttribute('title', expect.stringMatching(/Row and cabinet names/))
    await userEvent.setup().click(toggle)
    expect(props().cabinetLabels).toBe(false)
    const xray = screen.getByRole('button', { name: /X-ray/ })
    expect(xray).toHaveAttribute('aria-disabled', 'true')
    expect(xray).toHaveAttribute('title', 'X-ray: later')
    expect(xray).not.toBeDisabled() // stays focusable, does nothing
  })

  it('deep link ?device= opens the detail card: no Owner/Managed by/power/Move, Open cabinet link', async () => {
    renderWithProviders(<App />, '/halls/1/rows/1?device=1')
    const card = await screen.findByRole('region', { name: 'Device web-01' })
    expect(within(card).getByText('Status')).toBeInTheDocument()
    expect(within(card).getByText('U2–3 · 2U · front')).toBeInTheDocument()
    expect(within(card).getByText(/› Row 3 › R12$/)).toBeInTheDocument()
    expect(within(card).getByText('Depth')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(within(card).getByText('Serial')).toBeInTheDocument()
    expect(within(card).getByText('Asset type')).toBeInTheDocument()
    for (const banned of [/owner/i, /managed by/i, /power/i, /^move$/i]) expect(within(card).queryByText(banned)).toBeNull()
    expect(within(card).getByRole('link', { name: 'Open cabinet' })).toHaveAttribute('href', expect.stringMatching(/\/halls\/1\/cabinets\/\d+\?device=1$/))
    expect(props().selectedId).toBe(1)
    expect(props().tag).toEqual({ id: 1, text: 'web-01' }) // selected device gets a name tag; no always-on device names
  })

  it('pick selects, hover shows a tooltip card, Esc clears; toolbar drives the camera', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1')
    await screen.findByTestId('r3d-stub')
    const { act } = await import('@testing-library/react')
    act(() => props().onHover(1, 100, 100))
    expect(await screen.findByRole('tooltip')).toHaveTextContent('web-01')
    act(() => props().onPick(1))
    expect(await screen.findByRole('region', { name: 'Device web-01' })).toBeInTheDocument()
    expect(screen.queryByRole('tooltip')).toBeNull() // no hover card over the selection
    await user.click(screen.getByRole('button', { name: 'Rear' }))
    await user.click(screen.getByRole('button', { name: 'Next cabinet' }))
    await user.click(screen.getByRole('button', { name: 'Reset' }))
    expect(h.calls).toEqual(['side:rear', 'focus:1', 'preset:reset'])
    act(() => props().onView('rear'))
    expect(screen.getByText('Rear', { selector: '.chip' })).toBeInTheDocument()
    await user.selectOptions(screen.getByRole('combobox', { name: /Highlight/ }), 'status')
    expect(props().highlight).toBe('status')
    expect(screen.queryByRole('option', { name: /owner|managed|profile/i })).toBeNull()
    screen.getByRole('application').focus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('region', { name: 'Device web-01' })).toBeNull()
    expect(document.activeElement?.getAttribute('role')).toBe('application')
    await user.keyboard('{ArrowUp}')
    expect(props().selectedId).not.toBeNull()
    await user.keyboard('f+-')
    expect(h.calls).toEqual(expect.arrayContaining(['flip', 'zoom:0.8', 'zoom:1.25']))
  })

  it('List shows the same data as text; 2D link and fallbacks show the 2D row front', async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />, '/halls/1/rows/1')
    await screen.findByTestId('r3d-stub')
    await user.click(screen.getByRole('button', { name: 'List' }))
    expect(screen.getByRole('heading', { name: 'Devices in this row' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /U2–3 · web-01/ })).toHaveAttribute('aria-pressed', 'false')
    await user.click(screen.getByRole('button', { name: /U2–3 · web-01/ }))
    expect(screen.getByRole('button', { name: /U2–3 · web-01/ })).toHaveAttribute('aria-pressed', 'true') // list mirrors the selection
    await user.click(screen.getByRole('link', { name: '2D' }))
    expect(await screen.findByRole('grid', { name: 'Row cabinets, front view' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '3D' }))
    expect(await screen.findByTestId('r3d-stub')).toBeInTheDocument()
    const { act } = await import('@testing-library/react')
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    act(() => props().onFatal(new Error("Cannot read properties of null (reading 'precision')")))
    expect(await screen.findByText("3D view isn't available here. Showing the 2D row view.")).toBeInTheDocument()
    expect(screen.queryByText(/reading 'precision'/)?.closest('details')).not.toBeNull() // raw error only in Details
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
    expect(screen.getByRole('grid', { name: 'Row cabinets, front view' })).toBeInTheDocument()
  })

  it('no WebGL → 2D row front with a notice', async () => {
    h.webgl = false
    renderWithProviders(<App />, '/halls/1/rows/1')
    expect(await screen.findByText("3D view isn't available here. Showing the 2D row view.")).toBeInTheDocument()
    expect(await screen.findByRole('grid', { name: 'Row cabinets, front view' })).toBeInTheDocument()
  })
})

describe('3D selection announcements', () => {
  beforeEach(() => { resetAuth(); setCsrfToken('csrf-1'); localStorage.clear(); installMockApi(seedDb()); h.props = null; h.calls = []; h.webgl = true })
  it('aria-live line: "Selected: host, Cabinet X, RU a–b", then "Selection cleared"', async () => {
    const { act } = await import('@testing-library/react')
    renderWithProviders(<App />, '/halls/1/rows/1')
    await screen.findByTestId('r3d-stub')
    const live = screen.getByTestId('r3d-live')
    expect(live).toHaveAttribute('aria-live', 'polite')
    expect(live).toHaveTextContent(/^$/)
    act(() => props().onPick(1))
    expect(await screen.findByText('Selected: web-01, Cabinet R12, RU 2–3')).toBe(live)
    act(() => props().onPick(null))
    expect(await screen.findByText('Selection cleared')).toBe(live)
  })
})

