import type { UiProfile } from '../../api/profiles'
import { categoryOf } from '../../lib/rowFront'
import FallbackFront from '../rowfront/FallbackFront'

/** Small front thumbnail: the profile's thumb, else the generic face for its asset type. */
export default function ProfileThumb({ profile: p }: { profile: UiProfile }) {
  return (
    <span className="pp-thumb" aria-hidden="true">
      {p.frontImage ? <img src={p.frontImage.thumb_url} alt="" loading="lazy" decoding="async" /> : <FallbackFront category={p.assetType ? categoryOf(p.assetType) : 'other'} units={1} />}
    </span>
  )
}
