import { describe, expect, it } from 'vitest'
import { didYouMean, editDistance, normKey, suggest, uniqueValues } from './typeahead'

const MFRS = ['APC', 'Arista', 'Cisco', 'Dell', 'Hewlett Packard Enterprise', 'Juniper', 'Supermicro']

describe('typeahead', () => {
  it('unique values keep the first spelling', () => {
    expect(uniqueValues(['Dell', 'dell ', 'APC', null, '', 'Cisco'])).toEqual(['APC', 'Cisco', 'Dell'])
  })
  it('suggest: prefix, then word start, then substring (2+ chars); exact excluded', () => {
    expect(suggest('a', MFRS)).toEqual(['APC', 'Arista'])
    expect(suggest('pack', MFRS)).toEqual(['Hewlett Packard Enterprise'])
    expect(suggest('micro', MFRS)).toEqual(['Supermicro'])
    expect(suggest('Dell', MFRS)).toEqual([])
    expect(suggest('', MFRS, 3)).toEqual(['APC', 'Arista', 'Cisco'])
  })
  it('did you mean: case/space/punctuation and small typos', () => {
    expect(didYouMean('dell', MFRS)).toBe('Dell')
    expect(didYouMean('Super-Micro', MFRS)).toBe('Supermicro')
    expect(didYouMean('Junpier', MFRS)).toBe(null) // transposition = 2 edits on 7 chars
    expect(didYouMean('Junipr', MFRS)).toBe('Juniper')
    expect(didYouMean('Aristaa', MFRS)).toBe('Arista')
    expect(didYouMean('Supermicor', MFRS)).toBe('Supermicro')
    expect(didYouMean('Lenovo', MFRS)).toBe(null)
    expect(didYouMean('Dell', MFRS)).toBe(null)
    expect(didYouMean('HP', MFRS)).toBe(null) // too short to guess
    expect(normKey('Hewlett-Packard ')).toBe('hewlettpackard')
    expect(editDistance('kitten', 'sitting')).toBe(3)
  })
})
