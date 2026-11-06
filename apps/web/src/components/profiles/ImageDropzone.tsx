// PNG/JPEG/WebP drop or pick, with the D28 client pre-check (≤ 2 MiB, ≤ 4096 px, no SVG).
import { useState, type DragEvent } from 'react'
import { IMAGE_TYPES, imageProblem } from '../../api/profiles'
import { aspectWarning } from '../../lib/aspect'

async function pixelSize(file: File): Promise<{ w: number; h: number } | undefined> {
  if (typeof createImageBitmap !== 'function') return undefined
  try {
    const bmp = await createImageBitmap(file)
    const size = { w: bmp.width, h: bmp.height }
    bmp.close?.()
    return size
  } catch {
    return undefined
  }
}

export default function ImageDropzone({ label, file, onChange, optional = false, uHeight }: {
  label: string; file: File | null; onChange: (f: File | null) => void; optional?: boolean
  /** Profile U height for the aspect warning (warn only, ±15% of 10.86:U). */
  uHeight?: number
}) {
  const [error, setError] = useState<string | null>(null)
  const [warn, setWarn] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  async function take(f: File | undefined) {
    if (!f) return
    const px = imageProblem(f) ? undefined : await pixelSize(f)
    const problem = imageProblem(f) ?? imageProblem(f, px)
    setError(problem)
    setWarn(!problem && px && uHeight ? aspectWarning(px.w, px.h, uHeight) : null)
    onChange(problem ? null : f)
  }
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); void take(e.dataTransfer.files?.[0]) }
  return (
    <div className={`dropzone${over ? ' over' : ''}`} onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}>
      <label className="field">
        {label}{optional ? ' (optional)' : ''}
        <input type="file" aria-label={label} accept={IMAGE_TYPES.join(',')} onChange={(e) => void take(e.target.files?.[0])} />
      </label>
      <span className="hint">{file ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB` : 'Drop PNG/JPEG/WebP, max 2 MiB and 4096 px'}</span>
      {file && <button type="button" className="ghost" onClick={() => onChange(null)}>Remove</button>}
      {error && <span className="field-error" role="alert">{error}</span>}
      {warn && file && <span className="field-warn" role="status">⚠ {warn}</span>}
    </div>
  )
}
