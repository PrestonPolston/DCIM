import { needsReviewText } from '../lib/needsProfile'

/** "? Needs profile" badge for placed devices flagged needs_review (profiles.md §8). */
export default function NeedsProfileBlock({ reason, compact = false }: { reason?: string | null; compact?: boolean }) {
  const text = needsReviewText(reason)
  return (
    <span className="badge needs-profile" title={text}>
      <span className="icon" aria-hidden="true">?</span>{compact ? <span className="visually-hidden">Needs profile</span> : 'Needs profile'}
      <span className="visually-hidden">: {text}</span>
    </span>
  )
}
