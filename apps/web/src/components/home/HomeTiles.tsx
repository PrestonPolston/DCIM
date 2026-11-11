import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { daysLabel, daysSince, hrefForFilter, type DeviceIssues, type ParkedTile, type ProfileHealth, type NeedsReviewItem, type StaleDraftItem, type RecentlyRetiredItem } from '../../api/home'
import { issueLabel } from '../../api/profiles'
import { statusLabel } from '../../lib/status'

export function ReadinessBadge({ kind }: { kind: 'today' | 'parked' }) {
  return kind === 'today'
    ? <span className="home-badge home-badge-ok">Works with today’s data</span>
    : <span className="home-badge home-badge-parked">Needs jobs/DCREQ logic (parked)</span>
}

export function Tile({
  title, count, badge, loading, error, onRetry, empty, children, ariaLabel,
}: {
  title: string
  count?: number | string
  badge?: ReactNode
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  empty?: string | null
  children?: ReactNode
  ariaLabel?: string
}) {
  return (
    <section className="home-tile" aria-label={ariaLabel ?? (typeof count === 'number' ? `${title}, ${count}` : title)}>
      <header className="home-tile-head">
        <h2>
          {title}
          {count !== undefined && count !== '' && <span className="home-count">{count}</span>}
        </h2>
        {badge}
      </header>
      {loading && (
        <div className="home-skel" aria-busy="true" aria-label={`Loading ${title}`}>
          <div className="home-sk" /><div className="home-sk" style={{ width: '70%' }} /><div className="home-sk" style={{ width: '55%' }} />
        </div>
      )}
      {error && !loading && (
        <p className="home-alert" role="alert">
          Couldn’t load {title.toLowerCase()}.{' '}
          {onRetry && <button type="button" className="link" onClick={onRetry}>Retry</button>}
        </p>
      )}
      {!loading && !error && empty && <p className="hint">{empty}</p>}
      {!loading && !error && !empty && children}
    </section>
  )
}

export function ParkedCard({ title, tile, extra }: { title: string; tile: ParkedTile; extra?: ReactNode }) {
  return (
    <Tile title={title} badge={<ReadinessBadge kind="parked" />}>
      <p className="hint">Not available yet. {tile.message}</p>
      {extra}
    </Tile>
  )
}

export function ProfileHealthTile({
  data, loading, error, onRetry, canFix,
}: {
  data?: ProfileHealth
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  canFix: boolean
}) {
  const total = data ? data.needs_review.count + data.stale_drafts.count + data.recently_retired.count : undefined
  const empty = data && total === 0 ? 'Profiles look healthy.' : null
  return (
    <Tile title="Profile health" count={empty ? undefined : total} badge={<ReadinessBadge kind="today" />} loading={loading} error={error} onRetry={onRetry} empty={empty} ariaLabel={`Profile health, ${total ?? 0}`}>
      {data && !empty && (
        <>
          {data.needs_review.count > 0 && (
            <div className="home-sub">
              <p className="home-sub-title">⚠ Needs review <span className="home-count">{data.needs_review.count}</span></p>
              {data.needs_review.items.map((p: NeedsReviewItem) => (
                <div className="home-row" key={p.id}>
                  <span>
                    <b>{p.name}</b>
                    {p.usable_issue && <><br /><span className="hint">{issueLabel(p.usable_issue)}</span></>}
                  </span>
                  {canFix && <Link className="home-lk" to={hrefForFilter('/profiles', data.needs_review.filter)}>Fix</Link>}
                </div>
              ))}
              {data.needs_review.truncated && <p className="hint">Showing {data.needs_review.items.length} of {data.needs_review.count}.</p>}
            </div>
          )}
          <div className="home-sub">
            <p className="home-sub-title">Stale drafts <span className="home-count">{data.stale_drafts.count}</span> <span className="hint">(untouched ≥ 14 d)</span></p>
            {data.stale_drafts.items.map((p: StaleDraftItem) => {
              const age = daysSince(p.updated_at)
              return (
                <div className="home-row" key={p.id}>
                  <span><b>{p.name}</b>{age != null && <><br /><span className="hint">{daysLabel(age)}</span></>}</span>
                  {canFix && <Link className="home-lk" to={hrefForFilter('/profiles', data.stale_drafts.filter)}>Open</Link>}
                </div>
              )
            })}
          </div>
          <div className="home-sub">
            <p className="home-sub-title">Recently retired <span className="home-count">{data.recently_retired.count}</span></p>
            {data.recently_retired.items.map((p: RecentlyRetiredItem) => {
              const age = daysSince(p.retired_at)
              return (
                <div className="home-row" key={p.id}>
                  <span><b>{p.name}</b>{age != null && <><br /><span className="hint">{daysLabel(age)}</span></>}</span>
                  {canFix && <Link className="home-lk" to={hrefForFilter('/profiles', data.recently_retired.filter)}>Open</Link>}
                </div>
              )
            })}
          </div>
          <p className="home-tile-foot"><Link className="home-lk" to={hrefForFilter('/profiles', data.needs_review.filter)}>Profiles worklist</Link></p>
        </>
      )}
    </Tile>
  )
}

export function DeviceIssuesTile({
  data, loading, error, onRetry, canPlace,
}: {
  data?: DeviceIssues
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  canPlace: boolean
}) {
  const n = data?.no_position.count ?? 0
  const emptyPos = data && n === 0 ? 'All live devices have a position.' : null
  const href = data ? hrefForFilter('/devices', data.no_position.filter) : '/devices?status=install&status=active&unplaced=true'
  return (
    <Tile title="Device issues" loading={loading} error={error} onRetry={onRetry} ariaLabel={`Device issues, ${n} with no position`}>
      {data && (
        <>
          <div className="home-sub">
            <p className="home-sub-title"><ReadinessBadge kind="today" /> No position {n > 0 ? <span className="home-count">{n}</span> : null}</p>
            {emptyPos && <p className="hint">{emptyPos}</p>}
            {n > 0 && data.no_position.items.map((d) => (
              <div className="home-row" key={d.id}>
                <span className="home-row-main">
                  <span className="mono home-host" title={d.hostname}>{d.hostname}</span>
                  <span className="home-row-meta"> · {statusLabel(d.status)} · unplaced</span>
                </span>
                {canPlace && <Link className="home-lk" to={`${href}${href.includes('?') ? '&' : '?'}q=${encodeURIComponent(d.hostname)}`}>Place</Link>}
              </div>
            ))}
            {n > 0 && <p className="home-tile-foot"><Link className="home-lk" to={href}>{data.no_position.truncated ? `All ${n} unplaced` : `All ${n} unplaced`}</Link></p>}
          </div>
          <div className="home-parked-block">
            <p><ReadinessBadge kind="parked" /> <span className="hint">Power model not built (no PSU-assignment table)</span></p>
            <p className="hint" data-testid="power-parked">
              ⚡ Needs power assignment — —<br />
              Port conflicts — —<br />
              Open power mismatches — —<br />
              Not available yet. {data.needs_power_assignment.message}
            </p>
          </div>
        </>
      )}
    </Tile>
  )
}

export function WorkloadTile({ tile }: { tile: ParkedTile }) {
  return (
    <ParkedCard title="Workload" tile={tile} extra={
      <>
        <p className="hint">Open jobs per tech · jobs closed in the last 30 days · not a change log</p>
        <p className="home-tile-foot"><span className="hint">Audit log (later)</span></p>
      </>
    } />
  )
}
