// WebGL capability probe for choosing the 3D row view vs the 2D row front fallback.
let cached: boolean | null = null
export function hasWebGL(): boolean {
  if (cached != null) return cached
  try {
    if (typeof document === 'undefined' || typeof window === 'undefined' || !('WebGLRenderingContext' in window)) return (cached = false)
    const c = document.createElement('canvas')
    const gl = (c.getContext('webgl2') ?? c.getContext('webgl')) as WebGLRenderingContext | null
    cached = contextProblem(gl) == null
  } catch {
    cached = false
  }
  return cached
}
export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/** Plain-language fallback text for every 3D failure (no raw JS errors on screen). */
export const NO_3D_TEXT = "3D view isn't available here. Showing the 2D row view."

type GlLike = Pick<WebGLRenderingContext, 'isContextLost' | 'getShaderPrecisionFormat' | 'VERTEX_SHADER' | 'FRAGMENT_SHADER' | 'HIGH_FLOAT'>
/**
 * Why a context can't drive three.js, or null when it can. A context that is lost at creation
 * (Safari's per-page context limit, a GPU reset, a blocklisted driver) still exists but
 * getShaderPrecisionFormat() returns null, and three.js then crashes reading `.precision`.
 */
export function contextProblem(gl: GlLike | null | undefined): string | null {
  if (!gl) return 'no WebGL context'
  if (gl.isContextLost()) return 'WebGL context lost'
  for (const sh of [gl.VERTEX_SHADER, gl.FRAGMENT_SHADER]) if (!gl.getShaderPrecisionFormat(sh, gl.HIGH_FLOAT)) return 'WebGL precision formats unavailable (context lost or blocked)'
  return null
}
