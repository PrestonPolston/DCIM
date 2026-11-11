import { useMemo } from 'react'
import { useParams } from 'react-router'
import { useHallLayout, useLookups } from '../api/racks'
import FloorPlan from '../components/floorplan/FloorPlan'
import { useHallSettings } from '../components/floorplan/useHallSettings'
import { layoutHall } from '../lib/hallLayout'

export default function HallPage() {
  const id = Number(useParams().hallId)
  const { data, isPending, error } = useHallLayout(id)
  const [settings, update] = useHallSettings(id)
  const site = useLookups().sites.find((s) => s.id === data?.site_id)
  const geometry = useMemo(() => (data ? layoutHall(data.rows, settings) : null), [data, settings])
  if (isPending) return <p>Loading…</p>
  if (error) return <p className="error" role="alert">{error.message}</p>
  const horizontal = settings.aisle === 'horizontal'
  return (
    <section>
      <div className="page-header">
        <h1>{data.name}</h1>
        {site && <span className="hint">Building {site.name}{site.is_default ? ' (default)' : ''} · Room {data.name}</span>}
        <details className="popover">
          <summary className="button">Layout ▾</summary>
          <div className="card popover-body" role="group" aria-label="Layout settings">
            <label className="field">
              Aisle direction
              <select aria-label="Aisle direction" value={settings.aisle} onChange={(e) => update({ aisle: e.target.value as 'horizontal' | 'vertical' })}>
                <option value="horizontal">Horizontal (left ↔ right)</option>
                <option value="vertical">Vertical (top ↕ bottom)</option>
              </select>
            </label>
            <label className="field">
              Odd rows side
              <select aria-label="Odd rows side" value={settings.oddSide} onChange={(e) => update({ oddSide: e.target.value as 'start' | 'end' })}>
                <option value="start">{horizontal ? 'Top' : 'Left'}</option>
                <option value="end">{horizontal ? 'Bottom' : 'Right'}</option>
              </select>
            </label>
            <label className="field">
              Cabinet alignment
              <select aria-label="Cabinet alignment" value={settings.align} onChange={(e) => update({ align: e.target.value as 'start' | 'center' })}>
                <option value="start">Start</option>
                <option value="center">Center</option>
              </select>
            </label>
            <button type="button" onClick={() => update(null)}>Reset to default</button>
            <p className="hint">Saved in this browser only.</p>
          </div>
        </details>
      </div>
      {geometry!.warnings.length > 0 && (
        <ul className="banner" role="status">
          {geometry!.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      <FloorPlan hallId={id} geometry={geometry!} />
      <p className="hint">Legend: ▼▲ front edge · dashed = empty cabinet · ⚠ data issue</p>
    </section>
  )
}
