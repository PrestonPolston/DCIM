// Side panel for the selected device (row-front.md §3); full-screen sheet on phones via CSS.
import StatusControl from '../StatusControl'
import { deviceU, isNoSerial, type RowFrontDevice, type RowFrontRack } from '../../lib/rowFront'
import NoSerialBadge from '../NoSerialBadge'
import NeedsProfileBlock from '../NeedsProfileBlock'
import { needsProfile, needsReviewText } from '../../lib/needsProfile'

interface Props {
  device: RowFrontDevice
  rack: RowFrontRack
  canMove: boolean
  onClose: () => void
  /** Omitted on the cabinet page itself. */
  onOpenCabinet?: () => void
  onEdit: () => void
  onMove: () => void
}

export default function DeviceSidePanel({ device: d, rack, canMove, onClose, onOpenCabinet, onEdit, onMove }: Props) {
  const top = d.position_u + deviceU(d) - 1
  return (
    <aside className="rf-panel" aria-label={`Device ${d.host_name}`}>
      <div className="rf-panel-head">
        <h2 className="mono">{d.host_name}</h2>
        <button type="button" className="ghost icon" aria-label="Close" onClick={onClose}>✕</button>
      </div>
      <StatusControl device={{ ...d, rack_id: rack.id }} rackName={rack.name} />
      <p>{d.device_type ? `${d.device_type.manufacturer} ${d.device_type.name} · ${deviceU(d)}U` : 'No profile · 1U'}</p>
      <p>{rack.name} · {top === d.position_u ? `RU${top}` : `RU${d.position_u}–${top}`} · {d.face === 'front' ? 'Front' : 'Rear'}</p>
      {needsProfile(d) && <p><NeedsProfileBlock reason={d.needs_review_reason} /> <span className="hint">{needsReviewText(d.needs_review_reason)}</span></p>}
      <p>{isNoSerial(d) ? <NoSerialBadge note={d.serial_note} /> : <span className="mono">{d.serial_number}</span>}</p>
      <div className="rf-panel-actions">
        {onOpenCabinet && <button type="button" className="primary" onClick={onOpenCabinet}>Open cabinet ›</button>}
        {canMove && <button type="button" onClick={onEdit}>Edit</button>}
        {canMove && <button type="button" onClick={onMove}>Move</button>}
      </div>
    </aside>
  )
}
