import type { Face } from '../../api/types'
import { ZOOM_LEVELS } from '../../lib/rowFront'

export function FaceToggle({ face, onChange }: { face: Face; onChange: (f: Face) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Row face">
      <button type="button" aria-pressed={face === 'front'} onClick={() => onChange('front')}>Front (aisle)</button>
      <button type="button" aria-pressed={face === 'rear'} onClick={() => onChange('rear')}>Rear (back of row)</button>
    </div>
  )
}

export function ZoomControls({ fit, ru, onFit, onDetail, onStep }: {
  fit: boolean; ru: number; onFit: () => void; onDetail: () => void; onStep: (dir: 1 | -1) => void
}) {
  return (
    <div className="rf-zoom" role="group" aria-label="Zoom">
      <div className="segmented">
        <button type="button" aria-pressed={fit} onClick={onFit}>Fit</button>
        <button type="button" aria-pressed={!fit} onClick={onDetail}>Detail</button>
      </div>
      <button type="button" className="rf-zbtn" aria-label="Zoom out" onClick={() => onStep(-1)} disabled={!fit && ru <= ZOOM_LEVELS[0]}>−</button>
      <span className="mono" aria-live="polite">{fit ? `Fit · ${ru} px/RU` : `${ru} px/RU`}</span>
      <button type="button" className="rf-zbtn" aria-label="Zoom in" onClick={() => onStep(1)} disabled={ru >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]}>+</button>
    </div>
  )
}
