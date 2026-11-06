import { describe, expect, it } from 'vitest'
import { placeHoverCard } from './hoverCard'

const overlaps = (a: { left: number; top: number }, r: { left: number; top: number; right: number; bottom: number }, cw = 280, ch = 220) =>
  a.left < r.right && a.left + cw > r.left && a.top < r.bottom && a.top + ch > r.top

describe('placeHoverCard', () => {
  it('goes to the side with more free canvas and never covers the cabinet', () => {
    const cab = { left: 250, top: 100, right: 350, bottom: 600 }
    const p = placeHoverCard(cab, 300, 500, 1000, 700)
    expect(p.side).toBe('right')
    expect(overlaps(p, cab)).toBe(false)
    const right = { left: 700, top: 100, right: 800, bottom: 600 }
    const q = placeHoverCard(right, 750, 300, 1000, 700)
    expect(q.side).toBe('left')
    expect(q.left + 280).toBeLessThanOrEqual(700)
  })
  it('falls back above/below for a wide cabinet rect, and stays inside the canvas', () => {
    const wide = { left: 100, top: 300, right: 900, bottom: 450 }
    const p = placeHoverCard(wide, 500, 400, 1000, 800)
    expect(['above', 'below']).toContain(p.side)
    expect(overlaps(p, wide)).toBe(false)
    expect(p.left).toBeGreaterThanOrEqual(4); expect(p.left + 280).toBeLessThanOrEqual(996)
  })
})
