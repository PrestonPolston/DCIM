import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { jobHref, jobIntakeApi, isJobOverdue, type JobListParams, type JobStatus } from '../api/jobIntake'
import { useCan } from '../auth/auth'

const PAGE_SIZE = 50

export default function JobsPage() {
  const canWrite = useCan('job.write')
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') ?? '') as JobStatus | ''
  const overdue = params.get('overdue')
  const recentlyClosed = params.get('recently_closed')
  const q = params.get('q') ?? ''
  const offset = Number(params.get('offset') ?? 0)
  const [qInput, setQInput] = useState(q)
  const [debouncedQ, setDebouncedQ] = useState(q)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(qInput.trim()), 250)
    return () => clearTimeout(t)
  }, [qInput])

  const listParams: JobListParams = {
    status: status || undefined,
    overdue: overdue === 'true' ? true : overdue === 'false' ? false : undefined,
    recently_closed: recentlyClosed === 'true' ? true : recentlyClosed === 'false' ? false : undefined,
    q: debouncedQ || undefined,
    limit: PAGE_SIZE,
    offset,
  }
  const query = useQuery({
    queryKey: ['jobs', listParams],
    queryFn: () => jobIntakeApi().listJobs(listParams),
  })
  const jobs = query.data?.items ?? []
  const total = query.data?.total ?? 0

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'offset') next.delete('offset')
    setParams(next, { replace: true })
  }

  return (
    <section className="jobs-page">
      <div className="page-header">
        <h1>Jobs</h1>
        {canWrite && <Link className="button primary" to="/jobs/new">New job</Link>}
      </div>
      <div className="filters">
        <label className="field">
          Status
          <select aria-label="Status" value={status} onChange={(e) => setParam('status', e.target.value)}>
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <label className="field">
          Age
          <select aria-label="Age" value={overdue ?? ''} onChange={(e) => setParam('overdue', e.target.value)}>
            <option value="">All</option>
            <option value="true">Open more than 30 days</option>
            <option value="false">Not overdue</option>
          </select>
        </label>
        <label className="field">
          Recently closed
          <select aria-label="Recently closed" value={recentlyClosed ?? ''} onChange={(e) => setParam('recently_closed', e.target.value)}>
            <option value="">All</option>
            <option value="true">Closed in the last 30 days</option>
          </select>
        </label>
        <label className="field">
          Search
          <input type="search" aria-label="Search jobs" placeholder="DCREQ or name" value={qInput} onChange={(e) => { setQInput(e.target.value); setParam('q', e.target.value.trim()) }} />
        </label>
      </div>
      {query.isPending && <p className="hint">Loading…</p>}
      {query.error && <p className="error" role="alert">{query.error instanceof Error ? query.error.message : 'Failed to load jobs.'}</p>}
      {!query.isPending && jobs.length === 0 && <p className="hint">No jobs match these filters.</p>}
      {jobs.length > 0 && (
        <table className="table" aria-label="Jobs">
          <thead>
            <tr>
              <th>DCREQ</th>
              <th>Name</th>
              <th>Status</th>
              <th>Open items</th>
              <th>Days open</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const overdueFlag = job.overdue || isJobOverdue(job)
              return (
                <tr key={job.id}>
                  <td className="mono"><Link to={jobHref(job)}>{job.dcreq}</Link></td>
                  <td>{job.name}</td>
                  <td>
                    {job.status}
                    {overdueFlag && <span className="job-overdue">Open more than 30 days</span>}
                  </td>
                  <td>{job.unresolved_count}{job.deferred_count ? ` (${job.deferred_count} deferred)` : ''}</td>
                  <td>{job.days_open}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {total > PAGE_SIZE && (
        <div className="actions">
          <button type="button" disabled={offset <= 0} onClick={() => setParam('offset', String(Math.max(0, offset - PAGE_SIZE)))}>Previous</button>
          <span className="hint">{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
          <button type="button" disabled={offset + PAGE_SIZE >= total} onClick={() => setParam('offset', String(offset + PAGE_SIZE))}>Next</button>
        </div>
      )}
    </section>
  )
}
