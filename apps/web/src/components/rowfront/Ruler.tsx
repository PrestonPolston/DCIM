import { rulerLabels } from '../../lib/rowFront'

/** Sticky left RU ruler: labels every 5 RU, ticks every RU (one gradient), RU1 at the bottom. */
export default function Ruler({ rowU, ru, width, frame }: { rowU: number; ru: number; width: number; frame: number }) {
  return (
    <div className="rf-ruler" style={{ width, height: rowU * ru + frame * 2, ['--ru' as string]: `${ru}px`, paddingTop: frame }} aria-hidden="true">
      {rulerLabels(rowU).map((u) => (
        <span key={u} className="rf-ruler-n mono" style={{ top: frame + (rowU - u) * ru + ru / 2 }}>{u}</span>
      ))}
    </div>
  )
}
