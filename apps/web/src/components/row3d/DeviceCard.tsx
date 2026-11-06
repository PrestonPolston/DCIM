// Hover card (desktop pointer) and detail card for the 3D row (row-3d.md §5 field table).
// Per Preston: no Owner, no Managed by, no power fields, no Move (placement stays in 2D).
import { Link } from 'react-router'
import type { RowFrontDevice, RowFrontRack } from '../../lib/rowFront'
import { statusIcon, statusLabel } from '../../lib/status'
import { assetText, depthText, modelText, ORIENTATION_LABEL, serialText, sizeText } from '../../lib/deviceText'

interface Props {
  device: RowFrontDevice
  rack: RowFrontRack
  /** Profile variant name, shown only when it isn't the type's default. */
  variantName?: string | null
  path: string
  variant: 'hover' | 'detail'
  openHref?: string
  onEdit?: () => void
  onClose?: () => void
}

export default function DeviceCard({ device: d, rack, variantName, path, variant, openHref, onEdit, onClose }: Props) {
  const model = modelText(d)
  const profile = model ? `${model}${variantName ? ` (${variantName})` : ''}` : d.device_type ? null : 'No profile'
  const rows: [string, React.ReactNode][] = [
    ['Status', <><span aria-hidden="true">{statusIcon(d.status)}</span> {statusLabel(d.status)}</>],
    ['Profile', profile && <>{profile}{d.orientation && <> <span className="orient-badge">⇄ {ORIENTATION_LABEL[d.orientation].toUpperCase()}</span></>}</>],
    ['Asset type', assetText(d)],
    ['Serial', d.serial_number ? <span className="mono">{d.serial_number}</span> : <span className="no-serial">⚑ {serialText(d)}</span>],
    ['Position', sizeText(d)],
    ['Path', `${path} › ${rack.name}`],
    ['Depth', depthText(d)],
    ['Weight', d.weight_kg != null ? `${d.weight_kg} kg` : null],
  ]
  const thumbs = variant === 'detail' && (
    <div className="r3d-thumbs">
      {(['front', 'rear'] as const).map((f) => {
        const img = f === 'front' ? d.effective_front_image : d.effective_rear_image
        return (
          <figure key={f}>
            {img ? <img src={img.thumb_url} alt={`${f === 'front' ? 'Front' : 'Rear'} of ${d.host_name}`} loading="lazy" /> : <span className="r3d-thumb-missing">Generic art</span>}
            <figcaption>{f === 'front' ? 'Front' : 'Rear'}</figcaption>
          </figure>
        )
      })}
    </div>
  )
  return (
    <div className={`card r3d-card r3d-${variant}`} role={variant === 'hover' ? 'tooltip' : 'region'} aria-label={variant === 'detail' ? `Device ${d.host_name}` : undefined}>
      <div className="r3d-card-head">
        <strong className="r3d-card-title">{d.host_name}</strong>
        {onClose && <button type="button" className="ghost icon" aria-label="Close device details" onClick={onClose}>✕</button>}
      </div>
      <dl className="r3d-fields">
        {rows.filter(([, v]) => v != null && v !== '' && v !== false).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {thumbs}
      {variant === 'detail' && (
        <div className="actions">
          {onEdit && <button type="button" onClick={onEdit}>Edit</button>}
          {openHref && <Link to={openHref} className="button primary">Open cabinet</Link>}
        </div>
      )}
    </div>
  )
}
