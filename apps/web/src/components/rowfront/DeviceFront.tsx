// One device block in the row front view: image or fallback, LOD, overlays (row-front.md §2, §5).
import { memo, useState } from 'react'
import { statusClass, statusIcon, statusLabel } from '../../lib/status'
import { CATEGORY_LABEL, deviceCategory, deviceU, isNoSerial, type Lod, type RowFrontDevice } from '../../lib/rowFront'
import FallbackFront from './FallbackFront'
import NeedsProfileBlock from '../NeedsProfileBlock'
import { needsProfile } from '../../lib/needsProfile'

/** Session cache of image URL outcomes (one fetch per URL; failures stick). */
const imageState = new Map<string, 'ok' | 'failed'>()

export function StatusCorner({ status, lod }: { status: string; lod: Lod }) {
  return (
    <span className={`sc ${statusClass(status)} sc-l${lod}`} aria-hidden="true" title={statusLabel(status)}>
      {statusIcon(status)}
    </span>
  )
}

interface Props {
  device: RowFrontDevice
  lod: Lod
  ru: number
  passThrough: boolean
  conflict: boolean
}

function DeviceFront({ device: d, lod, ru, passThrough, conflict }: Props) {
  const img = d.effective_front_image
  const src = img ? (ru >= 32 ? img.url : img.thumb_url) : null
  const [, force] = useState(0)
  const failed = !!src && imageState.get(src) === 'failed'
  const cat = deviceCategory(d)
  const showImage = lod >= 1 && !!src && !failed && !passThrough
  const generic = lod >= 1 && !showImage && !passThrough
  const u = deviceU(d)
  return (
    <span className={`df ${statusClass(d.status)} df-l${lod}${passThrough ? ' pass' : ''}${conflict ? ' conflict' : ''}`}>
      {lod === 0 && <span className="df-fill" />}
      {showImage && (
        <img
          className="df-img" src={src!} alt="" loading="lazy" decoding="async" draggable={false}
          onLoad={() => imageState.set(src!, 'ok')}
          onError={() => { imageState.set(src!, 'failed'); force((n) => n + 1) }}
        />
      )}
      {generic && <FallbackFront category={cat} units={u} />}
      {generic && (
        <span className="df-placeholder" title={failed ? 'Image unavailable' : 'Generic image: no front image for this model'}>
          ◇{lod >= 2 && failed ? ' Image unavailable' : ''}
        </span>
      )}
      {d.status === 'decom' && lod >= 2 && <span className="df-decom" aria-hidden="true">DECOM</span>}
      {lod >= 1 && isNoSerial(d) && (
        <span className="df-noserial" title={`No serial${d.serial_note ? ` · ${d.serial_note}` : ''}`} aria-hidden="true">
          ⚑{lod >= 2 ? ' No serial' : ''}
        </span>
      )}
      {lod >= 2 && (
        <span className="df-label">
          <span className="df-host mono">{passThrough ? `${d.host_name} (${d.face}-mounted)` : d.host_name}</span>
          {u > 1 && !passThrough && (
            <span className="df-type">{d.device_type ? `${d.device_type.manufacturer} ${d.device_type.name}` : CATEGORY_LABEL.unknown}{generic && ` · ${CATEGORY_LABEL[cat]} · ${u}U`}</span>
          )}
        </span>
      )}
      {lod >= 2 && d.device_type && !d.device_type.is_full_depth && !passThrough && <span className="df-half" title="Half depth">½</span>}
      {lod >= 1 && needsProfile(d) && <span className="df-needs"><NeedsProfileBlock reason={d.needs_review_reason} compact={lod < 2} /></span>}
      <StatusCorner status={d.status} lod={lod} />
    </span>
  )
}

export default memo(DeviceFront)
