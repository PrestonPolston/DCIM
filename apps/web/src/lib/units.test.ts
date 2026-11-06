import { describe, expect, it } from 'vitest'
import { convertedText, fmtIn, inToMm, mmToIn, mmToInput, NUMBER_MSG, parseLength, parsePositive, parseUHeight, POSITIVE_MSG, roundHalfUp, U_HEIGHT_MSG } from './units'

describe('mm ↔ in', () => {
  it('converts with 25.4 and shows inches to 2 dp', () => {
    expect(mmToIn(600)).toBe(23.62)
    expect(mmToIn(1200)).toBe(47.24)
    expect(fmtIn(2470)).toBe('97.24 in')
    expect(fmtIn(25.4)).toBe('1.00 in')
  })
  it('cabinet: whole mm, half-up', () => {
    expect(inToMm(23.62)).toBe(600) // 599.948
    expect(inToMm(1)).toBe(25) // 25.4
    expect(inToMm(0.5)).toBe(13) // 12.7
    expect(inToMm(19)).toBe(483) // 482.6
    expect(inToMm(5 / 25.4 * 2.5)).toBe(13) // 12.5 exactly → up
  })
  it('device: 0.1 mm, half-up', () => {
    expect(inToMm(1.75, 'device')).toBe(44.5)
    expect(inToMm(17.24, 'device')).toBe(437.9) // 437.896
    expect(roundHalfUp(0.25, 0.1)).toBe(0.3)
    expect(roundHalfUp(1.005, 0.01)).toBe(1.01)
  })
  it('round trip in → mm → in is stable for cabinet sizes', () => {
    for (const mm of [600, 800, 1070, 1200, 1991, 2200, 2470]) expect(inToMm(mmToIn(mm))).toBe(mm)
  })
  it('input text per unit', () => {
    expect(mmToInput(600, 'mm')).toBe('600')
    expect(mmToInput(600, 'in')).toBe('23.62')
    expect(mmToInput(null, 'in')).toBe('')
  })
})

describe('parseLength / validation > 0', () => {
  it('accepts numbers, comma decimals and matching suffixes', () => {
    expect(parseLength('600', 'mm')).toMatchObject({ ok: true, mm: 600 })
    expect(parseLength(' 23,62 ', 'in')).toMatchObject({ ok: true, mm: 600 })
    expect(parseLength('23.62 in', 'in')).toMatchObject({ ok: true, mm: 600 })
    expect(parseLength('600mm', 'mm')).toMatchObject({ ok: true, mm: 600 })
    expect(parseLength('599.5', 'mm')).toMatchObject({ ok: true, mm: 600 })
  })
  it('empty is ok (checklist handles required)', () => {
    expect(parseLength('  ', 'mm')).toEqual({ ok: true, empty: true, mm: null })
  })
  it('> 0 only (no sanity ranges)', () => {
    expect(parseLength('0', 'mm')).toMatchObject({ ok: false, error: POSITIVE_MSG })
    expect(parseLength('-5', 'mm')).toMatchObject({ ok: false, error: POSITIVE_MSG })
    expect(parseLength('0.01', 'in')).toMatchObject({ ok: false, error: POSITIVE_MSG }) // rounds to 0 mm
    expect(parseLength('5', 'mm')).toMatchObject({ ok: true, mm: 5 })
    expect(parseLength('99999', 'mm')).toMatchObject({ ok: true, mm: 99999 })
  })
  it('non-numbers get the number message', () => {
    for (const t of ['abc', '6o0', '600 in', '1.2.3', '23.62 mm']) expect(parseLength(t, t.includes('mm') ? 'in' : 'mm').ok).toBe(false)
    expect(parseLength('abc', 'mm')).toMatchObject({ error: NUMBER_MSG })
  })
  it('converted text', () => {
    expect(convertedText('600', 'mm')).toBe('600 mm = 23.62 in')
    expect(convertedText('23.62', 'in')).toBe('23.62 in = 600 mm')
    expect(convertedText('x', 'mm')).toBeNull()
    expect(convertedText('', 'mm')).toBeNull()
  })
  it('U height 1–100 whole numbers', () => {
    expect(parseUHeight('53')).toEqual({ ok: true, value: 53 })
    for (const t of ['0', '101', '4.5', '-1', 'x']) expect(parseUHeight(t)).toEqual({ ok: false, error: U_HEIGHT_MSG })
    expect(parseUHeight('')).toEqual({ ok: true, value: null })
  })
  it('optional positive', () => {
    expect(parsePositive('1363')).toEqual({ ok: true, value: 1363 })
    expect(parsePositive('0')).toEqual({ ok: false, error: POSITIVE_MSG })
    expect(parsePositive('kg')).toEqual({ ok: false, error: NUMBER_MSG })
  })
})
