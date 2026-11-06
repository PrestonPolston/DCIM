import { rackU } from '../../lib/rack'
import type { RowFrontRack } from '../../lib/rowFront'

/** Sticky cabinet header: name, used/height, Install count, › to the elevation. */
export default function CabinetHeader({ rack, width, compact, onOpen }: { rack: RowFrontRack; width: number; compact: boolean; onOpen: () => void }) {
  const installs = rack.devices.filter((d) => d.status === 'install').length
  return (
    <div className="rf-head" style={{ width }}>
      <button type="button" className="rf-head-btn" onClick={onOpen} aria-label={`Open cabinet ${rack.name} elevation`} title={rack.name}>
        <span className="rf-head-name">{rack.name}</span>
        {!compact && <span aria-hidden="true">›</span>}
      </button>
      {!compact && (
        <span className="rf-head-meta mono">
          {rack.u_used}/{rackU(rack)}
          {installs > 0 && <span title={`${installs} Install`}> ◐{installs}</span>}
        </span>
      )}
    </div>
  )
}
