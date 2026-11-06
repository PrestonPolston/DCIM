/** Purple "⚑ No serial" badge, shown wherever serial_number is empty. */
export default function NoSerialBadge({ note }: { note?: string | null }) {
  return (
    <span className="no-serial-wrap">
      <span className="badge no-serial">
        <span className="icon" aria-hidden="true">⚑</span>No serial
      </span>
      {note && <span className="hint"> · {note}</span>}
    </span>
  )
}
