import { Link, useSearchParams } from 'react-router'
import { useHalls } from '../api/racks'
import { PARKED, parkedMyWork, useHomeSummary } from '../api/home'
import { useCan, useMe } from '../auth/auth'
import { can } from '../auth/permissions'
import { DeviceIssuesTile, ParkedCard, ProfileHealthTile, WorkloadTile } from '../components/home/HomeTiles'

/** Post-login home (`/`). Hall view lives at `/halls/:id`. */
export default function HomePage() {
  const me = useMe().data
  const isAdmin = can(me?.role, 'admin')
  const canFix = useCan('profile.publish')
  const canPlace = useCan('device.write')
  const canAddProfile = useCan('deviceType.create')
  const [params, setParams] = useSearchParams()
  const view = isAdmin && params.get('view') === 'admin' ? 'admin' : 'work'
  const setView = (next: 'work' | 'admin') => {
    const n = new URLSearchParams(params)
    if (next === 'admin') n.set('view', 'admin')
    else n.delete('view')
    setParams(n, { replace: true })
  }
  const summary = useHomeSummary()
  const myWork = summary.data?.my_work ?? parkedMyWork()
  const admin = isAdmin ? summary.data?.admin : undefined
  const halls = useHalls()
  const firstHall = halls.data?.items[0]
  const hallHref = firstHall ? `/halls/${firstHall.id}` : undefined
  const loadAdmin = isAdmin && view === 'admin'
  const err = summary.error ? summary.error.message : null
  const loading = loadAdmin && summary.isPending

  return (
    <section className="home-page">
      <div className="page-header">
        <h1>Home</h1>
        {isAdmin && (
          <div className="segmented" role="tablist" aria-label="Home view">
            <button type="button" role="tab" aria-selected={view === 'work'} onClick={() => setView('work')}>My work</button>
            <button type="button" role="tab" aria-selected={view === 'admin'} onClick={() => setView('admin')}>Admin</button>
          </div>
        )}
      </div>

      {view === 'work' && (
        <div className="home-work">
          <div className="home-intro" data-testid="home-empty-intro">
            <p>Nothing in work yet. Search for a device or open a hall.</p>
            <div className="home-intro-actions">
              {hallHref ? <Link className="button primary" to={hallHref}>Open hall</Link> : <span className="hint">No data halls yet.</span>}
              {canAddProfile && <Link className="button" to="/profiles?new=1">Add profile</Link>}
            </div>
          </div>
          <ParkedCard title="Jobs open more than 30 days" tile={myWork.jobs} />
          <div className="home-grid">
            <ParkedCard title="Current jobs" tile={myWork.jobs} />
            <ParkedCard title="Recent DCREQs" tile={myWork.dcreqs} />
          </div>
          <ParkedCard title="Held ePIF import rows" tile={myWork.held_imports} />
        </div>
      )}
      {view === 'admin' && (
        <div className="home-admin">
          <div className="home-grid">
            <ProfileHealthTile
              data={admin?.profile_health}
              loading={loading}
              error={err}
              onRetry={() => void summary.refetch()}
              canFix={canFix}
            />
            <DeviceIssuesTile
              data={admin?.device_issues}
              loading={loading}
              error={err}
              onRetry={() => void summary.refetch()}
              canPlace={canPlace}
            />
          </div>
          <WorkloadTile tile={admin?.workload ?? PARKED.workload} />
        </div>
      )}
    </section>
  )
}
