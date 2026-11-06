// Free-text combobox with suggestions and a "Did you mean X?" nudge (lib/typeahead).
import { useId, useMemo, useState } from 'react'
import { didYouMean, suggest } from '../../lib/typeahead'

export default function Typeahead({ label, value, onChange, options, required }: {
  label: string; value: string; onChange: (v: string) => void; options: string[]; required?: boolean
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const list = useMemo(() => suggest(value, options), [value, options])
  const hint = didYouMean(value, options)
  const showHint = !!hint && dismissed !== value && (!open || list.length === 0)
  const choose = (v: string) => { onChange(v); setOpen(false); setActive(-1) }
  const listId = `${id}-list`, hintId = `${id}-dym`
  return (
    <div className="field ta">
      <label htmlFor={`${id}-in`}>{label}{required ? ' *' : ''}</label>
      <input id={`${id}-in`} aria-label={label} role="combobox" aria-autocomplete="list" aria-expanded={open && list.length > 0} aria-controls={listId}
        aria-activedescendant={open && active >= 0 ? `${id}-o${active}` : undefined} aria-describedby={showHint ? hintId : undefined} autoComplete="off"
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && list.length) { e.preventDefault(); setOpen(true); setActive((a) => (a + 1) % list.length) }
          else if (e.key === 'ArrowUp' && list.length) { e.preventDefault(); setActive((a) => (a <= 0 ? list.length - 1 : a - 1)) }
          else if (e.key === 'Enter' && open && active >= 0 && list[active]) { e.preventDefault(); choose(list[active]) }
          else if (e.key === 'Escape') setOpen(false)
        }} />
      {open && list.length > 0 && (
        <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className="ta-list">
          {list.map((o, i) => (
            <li key={o} id={`${id}-o${i}`} role="option" aria-selected={i === active} className={i === active ? 'active' : undefined}
              onMouseDown={(e) => { e.preventDefault(); choose(o) }}>{o}</li>
          ))}
        </ul>
      )}
      <span id={hintId} className="hint ta-dym" aria-live="polite">
        {showHint && <>Did you mean <button type="button" className="link" onClick={() => choose(hint)}>{hint}</button>?
          <button type="button" className="ghost" aria-label={`Keep "${value}"`} onClick={() => setDismissed(value)}>Keep “{value}”</button></>}
      </span>
    </div>
  )
}
