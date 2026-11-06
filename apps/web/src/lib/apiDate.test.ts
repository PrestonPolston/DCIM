import { describe, expect, it } from 'vitest'
import { parseApiDate } from './apiDate'

describe('parseApiDate', () => {
  it('treats offset-less API timestamps as UTC', () => {
    expect(parseApiDate('2026-11-04T00:49:51.062242')!.toISOString()).toBe('2026-11-04T00:49:51.062Z')
    expect(parseApiDate('2026-11-04T00:49:51+00:00')!.toISOString()).toBe('2026-11-04T00:49:51.000Z')
    expect(parseApiDate('2026-11-04T00:49:51Z')!.toISOString()).toBe('2026-11-04T00:49:51.000Z')
    expect(parseApiDate('2026-11-03T18:49:51-06:00')!.toISOString()).toBe('2026-11-04T00:49:51.000Z')
  })
  it('null / junk → null', () => {
    expect(parseApiDate(null)).toBeNull()
    expect(parseApiDate('nope')).toBeNull()
  })
})
