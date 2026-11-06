import { statusClass, statusIcon, statusLabel } from '../lib/status'

/** Pill with icon + text; status is never conveyed by color alone. */
export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${statusClass(status)}`}>
      <span className="icon" aria-hidden="true">
        {statusIcon(status)}
      </span>
      {statusLabel(status)}
    </span>
  )
}
