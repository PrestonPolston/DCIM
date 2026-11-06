// Hover card placement (row-3d.md §5): never cover the hovered cabinet; prefer the side with more free canvas.
export interface Rect { left: number; top: number; right: number; bottom: number }

export function placeHoverCard(avoid: Rect | null, px: number, py: number, w: number, h: number, cw = 280, ch = 220, gap = 12): { left: number; top: number; side: 'right' | 'left' | 'above' | 'below' } {
  const clampY = (y: number) => Math.max(4, Math.min(h - ch - 4, y))
  const clampX = (x: number) => Math.max(4, Math.min(w - cw - 4, x))
  const a = avoid ?? { left: px, right: px, top: py, bottom: py }
  const freeR = w - a.right - gap, freeL = a.left - gap
  const sides: ['right' | 'left', number][] = freeR >= freeL ? [['right', freeR], ['left', freeL]] : [['left', freeL], ['right', freeR]]
  for (const [side, free] of sides) {
    if (free >= cw + 4) return { side, left: side === 'right' ? a.right + gap : a.left - gap - cw, top: clampY(py - 24) }
  }
  const freeB = h - a.bottom - gap, freeT = a.top - gap
  if (Math.max(freeB, freeT) >= ch + 4) {
    return freeB >= freeT ? { side: 'below', left: clampX(px - cw / 2), top: a.bottom + gap } : { side: 'above', left: clampX(px - cw / 2), top: a.top - gap - ch }
  }
  // Nothing fits fully: the roomier side, clamped into the canvas.
  const [side] = sides[0]
  return { side, left: clampX(side === 'right' ? a.right + gap : a.left - gap - cw), top: clampY(py - 24) }
}
