import { describe, expect, it } from 'vitest'
import { CABINET_FIXTURES, readinessOf } from '../api/cabinetProfiles.mock'
import { filterCabinets, cabinetChecklist, canSaveDraft, emptyCabinetForm, formFromProfile, missingSentence, profileChecklist, switchUnit, toBody, validateCabinet } from './cabinetForm'

const full = () => emptyCabinetForm({ manufacturer: 'APC', model: 'AR3300', len: { ...emptyCabinetForm().len, width_mm: '600', depth_mm: '1200', height_mm: '2470' } })

describe('cabinet form', () => {
  it('defaults: variant Standard, 53U, 19 in, mm', () => {
    expect(emptyCabinetForm()).toMatchObject({ name: 'Standard', uHeight: '53', rackUnitWidth: '19in', unit: 'mm' })
  })
  it('save draft needs manufacturer + model + variant only', () => {
    expect(canSaveDraft(emptyCabinetForm())).toBe(false)
    expect(canSaveDraft(emptyCabinetForm({ manufacturer: 'A', model: 'B' }))).toBe(true)
    expect(canSaveDraft(emptyCabinetForm({ manufacturer: 'A', model: 'B', name: ' ' }))).toBe(false)
  })
  it('unit switch converts valid values and keeps invalid text', () => {
    const f = { ...full(), len: { ...full().len, usable_width_mm: 'abc' } }
    const i = switchUnit(f, 'in')
    expect(i.len).toMatchObject({ width_mm: '23.62', depth_mm: '47.24', height_mm: '97.24', usable_width_mm: 'abc' })
    expect(switchUnit(i, 'mm').len).toMatchObject({ width_mm: '600', depth_mm: '1200', height_mm: '2470' })
  })
  it('body is always whole mm', () => {
    const b = toBody(switchUnit(full(), 'in'))
    expect(b).toMatchObject({ width_mm: 600, depth_mm: 1200, height_mm: 2470, u_height: 53, rack_unit_width: '19in', name: 'Standard', front_door: null, rail_depth_min_mm: null })
  })
  it('field errors: > 0, numbers, U height, rail min ≤ max, colour', () => {
    const f = emptyCabinetForm({ uHeight: '0', colorHex: 'red', len: { ...emptyCabinetForm().len, width_mm: '0', depth_mm: 'x', rail_depth_min_mm: '900', rail_depth_max_mm: '800' } })
    expect(validateCabinet(f)).toEqual({
      width_mm: 'Must be greater than 0.', depth_mm: 'Enter a number (e.g. 600 or 23.62).', u_height: 'U height must be a whole number from 1 to 100.',
      rail_depth_max_mm: 'Max must be at least the min.', color_hex: 'Use a colour like #1F1F1F.',
    })
    expect(validateCabinet(full())).toEqual({})
  })
})

describe('publish checklist', () => {
  it('lists every * item; images are not on it', () => {
    const items = cabinetChecklist(emptyCabinetForm())
    expect(items.map((i) => i.label)).toEqual(['Manufacturer', 'Model', 'Variant name', 'U height', 'Outer width', 'Outer depth', 'Outer height', 'Rack-unit width'])
  })
  it('missing sentence matches the copy', () => {
    const f = { ...full(), rackUnitWidth: '' as const, len: { ...full().len, depth_mm: '' } }
    expect(missingSentence(cabinetChecklist(f))).toBe('2 items missing: Outer depth, Rack-unit width.')
    expect(missingSentence(cabinetChecklist(full()))).toBe('Ready to publish.')
    expect(missingSentence(cabinetChecklist({ ...full(), uHeight: '' }))).toBe('1 item missing: U height.')
  })
  it('invalid values do not count as filled; server missing[] wins', () => {
    expect(cabinetChecklist({ ...full(), len: { ...full().len, width_mm: '0' } }).find((i) => i.key === 'width_mm')!.ok).toBe(false)
    expect(cabinetChecklist(full(), ['height_mm']).filter((i) => !i.ok).map((i) => i.key)).toEqual(['height_mm'])
  })
  it('saved profile checklist follows readiness', () => {
    const draft = { ...CABINET_FIXTURES[1], readiness: readinessOf(CABINET_FIXTURES[1]) }
    expect(missingSentence(profileChecklist(draft))).toBe('2 items missing: Outer depth, Rack-unit width.')
    expect(formFromProfile(draft, 'in').len.width_mm).toBe('31.5')
  })
})

describe('list filter', () => {
  const all = CABINET_FIXTURES.map((r) => ({ ...r, readiness: readinessOf(r) }))
  it('status tab + case-insensitive search over manufacturer, model, variant', () => {
    expect(filterCabinets(all, 'all', '').map((r) => r.id)).toEqual([1, 2, 3, 4])
    expect(filterCabinets(all, 'retired', '').map((r) => r.id)).toEqual([3])
    expect(filterCabinets(all, 'all', 'RITTAL').map((r) => r.id)).toEqual([2])
    expect(filterCabinets(all, 'all', 'standard').length).toBe(4)
    expect(filterCabinets(all, 'draft', 'apc')).toEqual([])
  })
})
