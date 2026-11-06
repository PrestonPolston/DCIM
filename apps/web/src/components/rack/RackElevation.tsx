import DeviceFront from '../rowfront/DeviceFront'
import { useState } from 'react'
import type { Face } from '../../api/types'
import { ALERT_STATUS, statusClass, statusIcon, statusLabel } from '../../lib/status'
import { COLLAPSE_MIN_EMPTY_RU } from '../../lib/rack'
import { needsReviewText } from '../../lib/needsProfile'
import NeedsProfileBlock from '../NeedsProfileBlock'
import { canPlace, emptyRuns, layoutFace, type Candidate, type ElevationDevice } from './layout'

export type ElevationView = Face | 'both'

interface Props {
  name?: string
  /** Rack height in U (API Rack.u_height). */
  uHeight: number
  devices: ElevationDevice[]
  view: ElevationView
  /** Collapse runs of >= COLLAPSE_MIN_EMPTY_RU empty U into one row. */
  collapseEmpty?: boolean
  onDeviceClick?: (d: ElevationDevice) => void
  /** Highlighted device (detail panel open). */
  selectedId?: number | null
  onEmptyClick?: (slot: { position_u: number; face: Face }) => void
  /** While set (dragging or click-to-place), empty RUs show valid/invalid targets. */
  placing?: Candidate | null
  /** A valid slot was dropped on or clicked while placing. */
  onPlace?: (slot: { position_u: number; face: Face }) => void
}

// Presentational rack elevation. U1 is at the bottom; one grid row per U whose
// height is --u-height (48px touch, 28px desktop compact).
export default function RackElevation({ view, ...rest }: Props) {
  const faces: Face[] = view === 'both' ? ['front', 'rear'] : [view]
  return (
    <div className={`elevation elevation-${view}`}>
      {faces.map((f) => (
        <RackFace key={f} face={f} {...rest} />
      ))}
    </div>
  )
}

function RackFace({
  face,
  name,
  uHeight,
  devices,
  collapseEmpty = false,
  onDeviceClick,
  selectedId,
  onEmptyClick,
  placing,
  onPlace,
}: Omit<Props, 'view'> & { face: Face }) {
  if (placing) collapseEmpty = false // every RU is a target during a drag
  const layout = layoutFace(uHeight, devices, face)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const row = (u: number) => uHeight - u + 1 // grid row for U (top = 1)
  const failed = layout.blocks.filter((b) => !b.mirrored && b.device.status === ALERT_STATUS).length
  const faceLabel = face === 'front' ? 'Front' : 'Rear'

  const emptyCells: React.ReactNode[] = []
  for (const run of emptyRuns(layout.empty)) {
    const top = run[0]
    const bottom = run[run.length - 1]
    if (collapseEmpty && run.length >= COLLAPSE_MIN_EMPTY_RU && !expanded.has(top)) {
      emptyCells.push(
        <button
          key={`c${top}`}
          type="button"
          className="u-empty u-collapsed"
          style={{ gridRow: `${row(top)} / span 1` }}
          onClick={() => setExpanded((s) => new Set(s).add(top))}
        >
          U{bottom}–U{top} · {run.length}U free
        </button>,
      )
      continue
    }
    for (const u of run) {
      const check = placing ? canPlace(uHeight, devices, placing, u, face) : null
      const slot = { position_u: u, face }
      if (!check && !onEmptyClick) {
        emptyCells.push(<div key={`e${u}`} className="u-empty" style={{ gridRow: row(u) }} aria-hidden="true" />)
        continue
      }
      emptyCells.push(
        <button
          key={`e${u}`}
          type="button"
          className={`u-empty${check ? (check.ok ? ' drop-ok' : ' drop-bad') : ''}`}
          style={{ gridRow: row(u) }}
          data-testid={`slot-${face}-${u}`}
          aria-label={
            check
              ? check.ok ? `Place at RU ${u}, ${face}` : `Cannot place at RU ${u}: ${check.reason}`
              : `Add device at U${u}, ${face}`
          }
          aria-disabled={check && !check.ok ? true : undefined}
          onClick={() => (check ? check.ok && onPlace?.(slot) : onEmptyClick?.(slot))}
          onDragOver={(e) => {
            if (check?.ok) {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
            }
          }}
          onDrop={(e) => {
            e.preventDefault()
            if (check?.ok) onPlace?.(slot)
          }}
        >
          <span aria-hidden="true">{check ? (check.ok ? '↓ drop here' : `✕ ${check.reason}`) : '+ add'}</span>
        </button>,
      )
    }
  }

  // When collapsed runs are present, rows only for the visible U.
  const collapsedRows = new Set<number>()
  if (collapseEmpty)
    for (const run of emptyRuns(layout.empty))
      if (run.length >= COLLAPSE_MIN_EMPTY_RU && !expanded.has(run[0])) run.slice(1).forEach((u) => collapsedRows.add(u))
  const rows = Array.from({ length: uHeight }, (_, i) => uHeight - i).map((u) =>
    collapsedRows.has(u) ? '0px' : 'var(--u-height)',
  )

  return (
    <section className="rack-face" aria-label={`${name ? `${name} ` : ''}${faceLabel}`}>
      <h3 className="rack-face-title">{faceLabel}</h3>
      <div className="rack-grid" style={{ gridTemplateRows: rows.join(' ') }}>
        {Array.from({ length: uHeight }, (_, i) => uHeight - i).map((u) =>
          collapsedRows.has(u) ? null : (
            <span key={`g${u}`} className="u-num mono" style={{ gridRow: row(u) }} aria-hidden="true">
              {u}
            </span>
          ),
        )}
        {emptyCells}
        {layout.blocks.map((b) => {
          const d = b.device
          const range = b.top === b.bottom ? `U${b.bottom}` : `U${b.bottom} to U${b.top}`
          return (
            <button
              key={d.id}
              type="button"
              data-testid={`device-${d.id}`}
              className={`u-device ${statusClass(d.status)}${d.needs_review ? ' needs-profile' : ''}${b.mirrored ? ' mirrored' : ''}${b.conflict ? ' conflict' : ''}${selectedId === d.id ? ' selected' : ''}${d.front && !b.mirrored ? ' has-art' : ''}`}
              aria-pressed={onDeviceClick ? selectedId === d.id : undefined}
              style={{ gridRow: `${row(b.top)} / span ${b.top - b.bottom + 1}` }}
              aria-label={`${d.host_name}, ${statusLabel(d.status)}, ${range}, ${d.face}${b.mirrored ? ' (shown from ' + face + ')' : ''}${d.serial_number === undefined ? '' : d.serial_number ? `, serial ${d.serial_number}` : ', no serial'}${d.needs_review ? ', needs profile' : ''}`}
              title={`${d.host_name} · ${statusLabel(d.status)} · ${range}${d.serial_number === undefined ? '' : d.serial_number ? ` · SN ${d.serial_number}` : ' · ⚑ No serial'}${d.needs_review ? ` · ? ${needsReviewText(d.needs_review_reason)}` : ''}`}
              onClick={() => onDeviceClick?.(d)}
            >
              {d.front && !b.mirrored && (
                <span className="u-device-art" aria-hidden="true">
                  <DeviceFront device={{ ...d.front, needs_review: false }} lod={1} ru={44} passThrough={false} conflict={false} />
                </span>
              )}
              {b.conflict && <span className="conflict-mark">⚠</span>}
              <span className="icon" aria-hidden="true">
                {statusIcon(d.status)}
              </span>
              <span className="u-device-name mono">{d.host_name}</span>
              {d.serial_number === null || d.serial_number === '' ? <span className="no-serial-flag" aria-hidden="true">⚑</span> : null}
              {d.needs_review && <NeedsProfileBlock reason={d.needs_review_reason} compact />}
              {b.mirrored ? (
                <span className="u-device-model">({d.face}-mounted)</span>
              ) : (
                <span className="u-device-model">{d.model ?? 'No profile'}</span>
              )}
            </button>
          )
        })}
      </div>
      <p className="rack-footer" data-testid={`footer-${face}`}>
        {layout.usedU}/{uHeight}U used · {uHeight - layout.usedU}U free · largest gap {layout.largestGap}U
        {failed > 0 && ` · ${failed} ${ALERT_STATUS}`}
        {layout.conflicts > 0 && ` · ${layout.conflicts} conflicts`}
      </p>
      {layout.unplaced.length > 0 && (
        <div className="unplaced">
          <h4>Unplaced devices</h4>
          <ul>
            {layout.unplaced.map((d) => (
              <li key={d.id} className="mono">
                {d.host_name} (U{d.position_u}, {d.height_u}U)
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
