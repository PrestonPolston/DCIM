import { describe, expect, it } from 'vitest'
import { aspectWarning, expectedAspect } from './aspect'

describe('aspectWarning (10.86:U, ±15%)', () => {
  it('accepts 1U/2U photos inside the band, with or without ears', () => {
    expect(expectedAspect(1).max).toBeCloseTo(10.857, 2)
    expect(aspectWarning(1086, 100, 1)).toBeNull()
    expect(aspectWarning(1010, 100, 1)).toBeNull()
    expect(aspectWarning(1200, 100, 1)).toBeNull() // +10.5%
    expect(aspectWarning(543, 100, 2)).toBeNull()
  })
  it('warns outside ±15% and guesses the U height', () => {
    expect(aspectWarning(543, 100, 1)).toMatch(/looks like a 2U photo/)
    expect(aspectWarning(1300, 100, 1)).toMatch(/13\.0:1/)
    expect(aspectWarning(0, 100, 1)).toBeNull()
  })
})
