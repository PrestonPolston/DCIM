// Phone / empty-RU "Choose profile" picker (profiles.md §3): full-screen list, same filters and footer.
import type { PlacingProfile } from '../../api/profiles'
import ProfilePalette from './ProfilePalette'

export default function ChooseProfileSheet({ onPick, onCancel, onAddProfile, context }: {
  onPick: (p: PlacingProfile) => void; onCancel: () => void; onAddProfile?: () => void; context?: string
}) {
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Choose profile">
      <div className="card sheet">
        <div className="form-header">
          <h2>Choose profile</h2>
          <button type="button" className="ghost icon" aria-label="Close" onClick={onCancel}>✕</button>
        </div>
        {context && <p className="hint">{context}</p>}
        <ProfilePalette variant="sheet" title="Choose profile" onPick={(p) => p && onPick(p)} onAddProfile={onAddProfile} />
      </div>
    </div>
  )
}
