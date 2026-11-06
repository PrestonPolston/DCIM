import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import FloorPlan from './FloorPlan'
import { layoutHall, type LayoutRowIn } from '../../lib/hallLayout'

const rows = (nRows: number, perRow: number, extra: string[] = []): LayoutRowIn[] =>
  [...Array.from({ length: nRows }, (_, i) => `Row ${i + 1}`), ...extra].map((name, i) => ({
    id: i + 1,
    name,
    racks: Array.from({ length: perRow }, (_, j) => ({ id: i * 1000 + j + 1, name: `C${i + 1}-${j + 1}`, u_height: j % 2 ? 42 : 53, device_count: j % 3, u_used: j, u_free: (j % 2 ? 42 : 53) - j })),
  }))

describe('FloorPlan', () => {
  it('draws aisle, pinned row labels, front edges and the unassigned strip', () => {
    render(<MemoryRouter><FloorPlan hallId={1} geometry={layoutHall(rows(2, 2, ['Spare']))} /></MemoryRouter>)
    expect(screen.getByLabelText('Center aisle')).toBeInTheDocument()
    expect(screen.getByText('Unassigned rows: no row number in name')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Cabinet C1-1,.*front faces S/ })).toHaveClass('front-S')
    expect(screen.getByRole('link', { name: /Cabinet C2-1,.*front faces N/ })).toHaveClass('front-N')
    expect(screen.getByRole('link', { name: /Cabinet C3-1,.*Front direction not set/ })).not.toHaveClass('front-N')
    expect(screen.getByRole('link', { name: 'Row 1' }).closest('.fp-label')).not.toBeNull()
    expect(screen.getByRole('link', { name: 'Row 1' })).toHaveAttribute('href', '/halls/1/rows/1')
  })

  it('mixed-height row: each tile reports its own height', () => {
    render(<MemoryRouter><FloorPlan hallId={1} geometry={layoutHall(rows(1, 2))} /></MemoryRouter>)
    expect(screen.getByRole('link', { name: /Cabinet C1-1, 0 of 53 RU used, 53 free/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Cabinet C1-2, 1 of 42 RU used, 41 free/ })).toBeInTheDocument()
  })

  it('renders 420 cabinets in reasonable time', () => {
    const t = performance.now()
    render(<MemoryRouter><FloorPlan hallId={1} geometry={layoutHall(rows(20, 21))} /></MemoryRouter>)
    expect(screen.getAllByRole('link', { name: /^Cabinet / })).toHaveLength(420)
    expect(performance.now() - t).toBeLessThan(3000)
  })
})
