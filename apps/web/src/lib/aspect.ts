// Photo aspect check vs the rack face (ROW_3D_SPIKE.md §5): a U-high face is 482.6 mm wide
// (with ears; ~450 mm without) × U × 44.45 mm tall → 10.86:U (10.1:U without ears).
// Warn only, never block, when a photo is more than ±15% outside that band.
export const RU_MM = 44.45
export const FACE_W_EARS_MM = 482.6
export const FACE_W_NO_EARS_MM = 450
export const ASPECT_TOLERANCE = 0.15

export function expectedAspect(u: number) {
  return { min: FACE_W_NO_EARS_MM / (u * RU_MM), max: FACE_W_EARS_MM / (u * RU_MM) }
}

/** null when fine or unknown; otherwise a warning sentence for the uploader. */
export function aspectWarning(w: number, h: number, u: number): string | null {
  if (!(w > 0) || !(h > 0) || !(u >= 1)) return null
  const r = w / h
  const { min, max } = expectedAspect(u)
  if (r >= min * (1 - ASPECT_TOLERANCE) && r <= max * (1 + ASPECT_TOLERANCE)) return null
  // Which U height would this photo fit?
  const guess = Math.max(1, Math.round(FACE_W_EARS_MM / (r * RU_MM)))
  return `This photo is ${r.toFixed(1)}:1; a ${u}U face is about ${max.toFixed(1)}:1.${guess !== u ? ` It looks like a ${guess}U photo.` : ''} Crop to the chassis, straight on.`
}
