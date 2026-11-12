import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { jobIntakeApi } from '../api/jobIntake'
import { useCan } from '../auth/auth'

/** Thin job header so "Open that job" and the post-commit link are not dead. Queue UI is a later slice. */
export default function JobPage() {
  const { idOrDcreq = '' } = useParams()
  const canWrite = useCan('job.write')
  const q = useQuery({
    queryKey: ['jobs', idOrDcreq],
    queryFn: () => jobIntakeApi().getJob(idOrDcreq),
    enabled: !!idOrDcreq,
  })
  const job = q.data
  const err = q.error instanceof ApiError ? q.error.message : q.error instanceof Error ? q.error.message : null

  return (
    <section className="job-page">
      <div className="page-header">
        <h1>{job ? job.dcreq : 'Job'}</h1>
        {canWrite && <Link className="button" to="/jobs/new">New job</Link>}
      </div>
      {q.isPending && <p className="hint">Loading…</p>}
      {err && <p className="error" role="alert">{err}</p>}
      {job && (
        <div className="card">
          <p role="status">{job.name} · {job.status}{job.overdue ? ' · open more than 30 days' : ''}</p>
          <p className="hint">{job.device_count} devices · {job.connection_count ?? 0} connections · {job.unresolved_count} in the fill-later queue.</p>
          <p className="hint">The fill-later queue and close/reopen actions will land in a later slice.</p>
        </div>
      )}
    </section>
  )
}
