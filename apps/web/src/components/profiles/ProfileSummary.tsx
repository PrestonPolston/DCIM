// Read-only profile summary in the device form (profiles.md §7).
import { ASSET_LABEL, profileTitle, specLine, variantOf, type UiProfile } from '../../api/profiles'
import ProfileThumb from './ProfileThumb'

export default function ProfileSummary({ profile, label, onChange }: { profile: UiProfile | null; label?: string; onChange?: () => void }) {
  return (
    <div className="profile-summary" role="group" aria-label="Profile">
      {profile ? (
        <>
          <ProfileThumb profile={profile} />
          <span className="pp-text">
            <strong>{profileTitle(profile)}</strong>
            {variantOf(profile) && <span className="hint">{variantOf(profile)}</span>}
            <span className="hint">{specLine(profile)} · {ASSET_LABEL[profile.assetType ?? 'unknown'] ?? profile.assetType}</span>
          </span>
        </>
      ) : <span>{label ?? 'Profile'}</span>}
      {onChange && <button type="button" className="ghost" onClick={onChange}>Change profile</button>}
    </div>
  )
}
