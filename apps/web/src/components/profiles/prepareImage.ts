// Client-side prep before PUT (mobile.md photo rules, D28): decode, downscale to ≤ 2048 px,
// re-encode JPEG/WebP under 2 MiB. HEIC needs a decoder the browser lacks → reported, not uploaded.
import { HEIC_TEXT, IMAGE_MAX_BYTES, isHeic } from '../../api/profiles'

export const MAX_SIDE = 2048
export interface Prepared { blob: Blob; w: number; h: number; resized: boolean }

export async function prepareImage(file: File): Promise<Prepared> {
  if (isHeic(file)) throw new Error(HEIC_TEXT)
  if (typeof createImageBitmap !== 'function') return { blob: file, w: 0, h: 0, resized: false }
  const bmp = await createImageBitmap(file)
  const { width: w, height: h } = bmp
  const scale = Math.min(1, MAX_SIDE / Math.max(w, h))
  if (scale === 1 && file.size <= IMAGE_MAX_BYTES && /^image\/(png|jpeg|webp)$/.test(file.type)) { bmp.close?.(); return { blob: file, w, h, resized: false } }
  const cw = Math.round(w * scale), ch = Math.round(h * scale)
  const cv = document.createElement('canvas'); cv.width = cw; cv.height = ch
  cv.getContext('2d')!.drawImage(bmp, 0, 0, cw, ch)
  bmp.close?.()
  for (const q of [0.9, 0.8, 0.7, 0.6]) {
    const blob = await new Promise<Blob | null>((r) => cv.toBlob(r, 'image/jpeg', q))
    if (blob && blob.size <= IMAGE_MAX_BYTES) return { blob, w: cw, h: ch, resized: true }
  }
  throw new Error('Couldn’t get the image under 2 MiB.')
}
