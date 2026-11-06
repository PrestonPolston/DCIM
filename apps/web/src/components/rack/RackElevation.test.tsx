import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RackElevation from './RackElevation'
import { layoutFace, emptyRuns, type ElevationDevice } from './layout'

const dev = (p: Partial<ElevationDevice> & { id: number }): ElevationDevice => ({
  host_name: `dev-${p.id}`, status: 'active', position_u: 1, height_u: 1, face: 'front', ...p,
})

describe('layoutFace', () => {
  it('computes used/free and largest gap', () => {
    const l = layoutFace(10, [dev({ id: 1, position_u: 1, height_u: 2 }), dev({ id: 2, position_u: 6 })], 'front')
    expect(l.usedU).toBe(3)
    expect(l.largestGap).toBe(4) // U7..U10
    expect(l.empty).toEqual([10, 9, 8, 7, 5, 4, 3])
    expect(emptyRuns(l.empty)).toEqual([[10, 9, 8, 7], [5, 4, 3]])
  })

  it('shows full-depth devices on both faces, half-depth only on its face', () => {
    const devices = [dev({ id: 1, position_u: 1 }), dev({ id: 2, position_u: 2, is_full_depth: false })]
    const rear = layoutFace(4, devices, 'rear')
    expect(rear.blocks.map((b) => [b.device.id, b.mirrored])).toEqual([[1, true]])
    expect(rear.empty).toContain(2)
  })

  it('flags overlaps and lists devices above the rack as unplaced', () => {
    const l = layoutFace(4, [dev({ id: 1, position_u: 1, height_u: 2 }), dev({ id: 2, position_u: 2 }), dev({ id: 3, position_u: 4, height_u: 2 })], 'front')
    expect(l.conflicts).toBe(2)
    expect(l.unplaced.map((d) => d.id)).toEqual([3])
  })
})

describe('RackElevation', () => {
  it('renders U1 at the bottom and sizes devices by height_u', () => {
    render(<RackElevation uHeight={4} view="front" devices={[dev({ id: 1, host_name: 'web-01', position_u: 2, height_u: 2 })]} />)
    const nums = screen.getAllByText(/^[1-4]$/).map((n) => n.textContent)
    expect(nums).toEqual(['4', '3', '2', '1'])
    const block = screen.getByRole('button', { name: 'web-01, Active, U2 to U3, front' })
    expect(block.style.gridRow).toBe('2 / span 2') // U3 is grid row 2 in a 4U rack
  })

  it('renders both faces with the opposite face hatched', () => {
    render(<RackElevation uHeight={2} view="both" devices={[dev({ id: 1, host_name: 'sw-01' })]} />)
    const rear = screen.getByRole('region', { name: 'Rear' })
    expect(within(rear).getByText('(front-mounted)')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Front' })).toBeInTheDocument()
  })

  it('reports empty slot and device clicks', async () => {
    const user = userEvent.setup()
    const onEmpty = vi.fn()
    const onDevice = vi.fn()
    render(<RackElevation uHeight={2} view="rear" devices={[dev({ id: 1, face: 'rear', status: 'decom' })]} onEmptyClick={onEmpty} onDeviceClick={onDevice} />)
    await user.click(screen.getByRole('button', { name: 'Add device at U2, rear' }))
    expect(onEmpty).toHaveBeenCalledWith({ position_u: 2, face: 'rear' })
    await user.click(screen.getByTestId('device-1'))
    expect(onDevice).toHaveBeenCalled()
    expect(screen.getByTestId('footer-rear').textContent).toContain('1/2U used · 1U free · largest gap 1U')
  })

  it('collapses runs of 4+ empty U and expands on tap', async () => {
    const user = userEvent.setup()
    render(<RackElevation uHeight={7} view="front" collapseEmpty devices={[dev({ id: 1 })]} onEmptyClick={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'U2–U7 · 6U free' }))
    expect(screen.getByRole('button', { name: 'Add device at U4, front' })).toBeInTheDocument()
  })
})

import { canPlace } from './layout'
describe('canPlace', () => {
  const devices = [dev({ id: 1, host_name: 'a', position_u: 3, height_u: 2, is_full_depth: false })]
  it('rejects out of bounds and same-face overlaps', () => {
    expect(canPlace(5, devices, { height_u: 2, is_full_depth: false }, 5, 'front')).toEqual({ ok: false, reason: 'exceeds RU5' })
    expect(canPlace(5, devices, { height_u: 1, is_full_depth: false }, 4, 'front')).toEqual({ ok: false, reason: 'overlaps a' })
  })
  it('allows the opposite face for half-depth, blocks it for full-depth', () => {
    expect(canPlace(5, devices, { height_u: 1, is_full_depth: false }, 4, 'rear').ok).toBe(true)
    expect(canPlace(5, devices, { height_u: 1, is_full_depth: true }, 4, 'rear').ok).toBe(false)
  })
  it('ignores the device being moved', () => {
    expect(canPlace(5, devices, { height_u: 2, is_full_depth: false, excludeId: 1 }, 2, 'front').ok).toBe(true)
  })
})

describe('cabinet heights', () => {
  it('draws a 53U cabinet with U53 at the top and U1 at the bottom', () => {
    render(<RackElevation uHeight={53} view="front" devices={[dev({ id: 1, host_name: 'top', position_u: 52, height_u: 2 })]} />)
    const nums = screen.getAllByText(/^\d+$/).map((n) => n.textContent)
    expect(nums[0]).toBe('53')
    expect(nums[nums.length - 1]).toBe('1')
    expect(nums).toHaveLength(53)
    expect(screen.getByRole('button', { name: /top, Active, U52 to U53/ }).style.gridRow).toBe('1 / span 2')
    expect(screen.getByTestId('footer-front').textContent).toContain('2/53U used')
  })
  it('mixed heights side by side: each cabinet uses its own u_height', () => {
    render(
      <>
        <RackElevation name="A" uHeight={53} view="front" devices={[]} />
        <RackElevation name="B" uHeight={42} view="front" devices={[]} />
      </>,
    )
    expect(screen.getByRole('region', { name: 'A Front' }).querySelector('.rack-grid')!.getAttribute('style')).toContain('var(--u-height)')
    expect(within(screen.getByRole('region', { name: 'A Front' })).getByTestId('footer-front').textContent).toContain('0/53U')
    expect(within(screen.getByRole('region', { name: 'B Front' })).getByTestId('footer-front').textContent).toContain('0/42U')
    expect(within(screen.getByRole('region', { name: 'B Front' })).queryByText('43')).toBeNull()
  })
})

import { DEFAULT_RACK_U, rackU } from '../../lib/rack'
describe('rackU', () => {
  it('uses API u_height and falls back to DEFAULT_RACK_U (53)', () => {
    expect(rackU({ u_height: 42 })).toBe(42)
    expect(rackU({})).toBe(DEFAULT_RACK_U)
    expect(DEFAULT_RACK_U).toBe(53)
  })
})
