// Devices flagged by the API as needing review (D31/D32): placed without a
// profile, or on a profile that isn't published. Pure helpers, no React.
import type { NeedsReview } from '../api/types'

const REASONS: Record<string, string> = {
  placed_without_profile: 'Placed without a profile. Choose a profile.',
  profile_not_published: "Its profile isn't published yet. Publish the profile or choose another.",
}

export const needsProfile = (d: NeedsReview | null | undefined) => d?.needs_review === true

export function needsReviewText(reason: string | null | undefined): string {
  return (reason && REASONS[reason]) || (reason ? `Needs review: ${reason}` : 'Needs review: choose a profile.')
}

/** Drawn as 1U blocking both faces when there's no profile geometry to use (API _LEGACY_OCCUPANT rule). */
export function drawAsPlaceholder(d: NeedsReview & { device_type?: unknown }): boolean {
  return d.device_type == null || (needsProfile(d) && d.needs_review_reason === 'placed_without_profile')
}
