import { describe, expect, it } from 'vitest'
import { contextProblem } from './webgl'

const gl = (o: { lost?: boolean; precision?: boolean } = {}) => ({
  VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, HIGH_FLOAT: 3,
  isContextLost: () => !!o.lost,
  getShaderPrecisionFormat: () => (o.precision === false ? null : { precision: 23, rangeMin: 127, rangeMax: 127 }),
}) as never

describe('contextProblem (the null "precision" crash)', () => {
  it('accepts a healthy context and rejects null, lost, or precision-less ones', () => {
    expect(contextProblem(gl())).toBeNull()
    expect(contextProblem(null)).toMatch(/no WebGL/)
    expect(contextProblem(gl({ lost: true }))).toMatch(/lost/)
    expect(contextProblem(gl({ precision: false }))).toMatch(/precision/)
  })
})
