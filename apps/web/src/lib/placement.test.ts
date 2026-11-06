import { describe, expect, it } from 'vitest'
import { autoScrollDelta, checkFit, describeMove, keyMoveStep, moveBody, positionFromTop } from './placement'

const d = (id: number, position_u: number, height_u: number, face: 'front' | 'rear' = 'front', full = true) =>
  ({ id, host_name: `h${id}`, status: 'active', position_u, height_u, face, is_full_depth: full })

describe('placement', () => {
  it('fit rules: bounds, overlap same face or full depth, ignores itself', () => {
    const devs = [d(1, 10, 2), d(2, 20, 1, 'rear', false)]
    expect(checkFit(53, devs, d(1, 10, 2), 52, 'front')).toEqual({ ok: true })
    expect(checkFit(53, devs, d(1, 10, 2), 53, 'front')).toEqual({ ok: false, reason: 'exceeds RU53' })
    expect(checkFit(42, devs, d(1, 10, 2), 42, 'front')).toEqual({ ok: false, reason: 'exceeds RU42' })
    expect(checkFit(53, devs, d(9, 1, 1, 'front', false), 20, 'front')).toEqual({ ok: true })
    expect(checkFit(53, devs, d(9, 1, 1, 'front', true), 20, 'front')).toEqual({ ok: false, reason: 'overlaps h2' })
    expect(checkFit(53, devs, d(1, 10, 2), 11, 'front')).toEqual({ ok: true })
  })
  it('describes the move and builds the PATCH body', () => {
    const from = { rackId: 4, rackName: 'C-B04', position_u: 20, face: 'front' as const }
    const to = { rackId: 7, rackName: 'C-B07', position_u: 12, face: 'front' as const }
    expect(describeMove('web-01', from, to)).toBe('Move web-01: C-B04 RU20 Front → C-B07 RU12 Front')
    expect(moveBody(to)).toEqual({ rack_id: 7, position_u: 12, face: 'front' })
    expect(positionFromTop(21, 2)).toBe(20)
  })
  it('keyboard move steps clamp to each cabinet height', () => {
    const cols = [{ u: 53 }, { u: 42 }]
    const m = { col: 0, position_u: 52, face: 'front' as const }
    expect(keyMoveStep(m, 'ArrowUp', cols, 2)).toEqual({ ...m, position_u: 52 })
    expect(keyMoveStep(m, 'ArrowRight', cols, 2)).toEqual({ col: 1, position_u: 41, face: 'front' })
    expect(keyMoveStep(m, 'f', cols, 2)?.face).toBe('rear')
    expect(keyMoveStep(m, 'q', cols, 2)).toBeNull()
  })
  it('auto-scroll speed grows near edges, max 20 px/frame', () => {
    expect(autoScrollDelta(200, 400)).toBe(0)
    expect(autoScrollDelta(0, 400)).toBe(-20)
    expect(autoScrollDelta(400, 400)).toBe(20)
    expect(autoScrollDelta(24, 400)).toBe(-10)
  })
})
