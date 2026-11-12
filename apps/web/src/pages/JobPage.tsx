import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import {
  JOB_INTAKE_API,
  closeOpenItemsWarning,
  humanizeItemType,
  isJobHasOpenItems,
  isJobOverdue,
  jobIntakeApi,
  type CloseWarning,
  type JobOpenItem,
  type OpenItemListStatus,
} from '../api/jobIntake'
import { useCan } from '../auth/auth'

const FILTERS: { id: OpenItemListStatus; label: string }[] = [
  { id: 'unresolved', label: 'Unresolved' },
  { id: 'open', label: 'Open' },
  { id: 'deferred', label: 'Deferred' },
  { id: 'resolved', label: 'Resolved' },
  { id: 'dismissed', label: 'Dismissed' },
  { id: 'all', label: 'All' },
]

function groupByType(items: JobOpenItem[]): [string, JobOpenItem[]][] {
  const order: string[] = []
  const groups = new Map<string, JobOpenItem[]>()
  for (const item of items) {
    if (!groups.has(item.item_type)) {
      groups.set(item.item_type, [])
      order.push(item.item_type)
    }
    groups.get(item.item_type)!.push(item)
  }
  return order.map((t) => [t, groups.get(t)!])
}

export default function JobPage() {
  const { idOrDcreq = '' } = useParams()
  const canWrite = useCan('job.write')
  const canTrack = useCan('job.track')
  const qc = useQueryClient()
  const [filter, setFilter] = useState<OpenItemListStatus>('unresolved')
  const [closeWarning, setCloseWarning] = useState<CloseWarning | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dismissFor, setDismissFor] = useState<number | null>(null)
  const [dismissNote, setDismissNote] = useState('')

  const jobQuery = useQuery({
    queryKey: ['jobs', idOrDcreq],
    queryFn: () => jobIntakeApi().getJob(idOrDcreq),
    enabled: !!idOrDcreq,
  })
  const job = jobQuery.data

  const itemsQuery = useQuery({
    queryKey: ['jobs', job?.id, 'open-items', filter],
    queryFn: () => jobIntakeApi().listOpenItems(job!.id, filter),
    enabled: typeof job?.id === 'number',
  })
  const items = itemsQuery.data?.items ?? []
  const groups = groupByType(items)

  function invalidate() {
    void qc.invalidateQueries({ queryKey: ['jobs'] })
  }

  const closeMut = useMutation({
    mutationFn: (acknowledge: boolean) => jobIntakeApi().closeJob(job!.id, { acknowledge_open_items: acknowledge }),
    onSuccess: (result) => {
      setCloseWarning(null)
      setError(null)
      void qc.setQueryData(['jobs', idOrDcreq], result.job)
      invalidate()
    },
    onError: (e) => {
      if (isJobHasOpenItems(e)) setCloseWarning(closeOpenItemsWarning(e))
      else setError(e instanceof Error ? e.message : 'Close failed.')
    },
  })

  const reopenMut = useMutation({
    mutationFn: () => jobIntakeApi().reopenJob(job!.id),
    onSuccess: (next) => {
      setError(null)
      void qc.setQueryData(['jobs', idOrDcreq], next)
      invalidate()
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Reopen failed.'),
  })

  async function runItem(op: () => Promise<unknown>) {
    setError(null)
    try {
      await op()
      invalidate()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That change could not be saved.')
    }
  }

  const jobErr = jobQuery.error instanceof ApiError ? jobQuery.error.message : jobQuery.error instanceof Error ? jobQuery.error.message : null
  const overdueFlag = job ? (job.overdue || isJobOverdue(job)) : false
  const unresolvedFromItems = itemsQuery.data && filter === 'unresolved' ? items.length : job?.unresolved_count
  const localWrites = JOB_INTAKE_API.live && !JOB_INTAKE_API.openItemWrites

  return (
    <section className="job-page">
      <div className="page-header">
        <h1>{job ? job.dcreq : 'Job'}</h1>
        <div className="actions">
          <Link className="button" to="/jobs">All jobs</Link>
          {canWrite && <Link className="button" to="/jobs/new">New job</Link>}
        </div>
      </div>
      {jobQuery.isPending && <p className="hint">Loading…</p>}
      {jobErr && <p className="error" role="alert">{jobErr}</p>}
      {job && (
        <>
          <div className="card">
            <p role="status">
              {job.name} · {job.status}
              {overdueFlag && <span className="job-overdue">Open more than 30 days</span>}
            </p>
            <p className="hint">
              {job.device_count} devices · {job.connection_count ?? 0} connections · {unresolvedFromItems ?? job.unresolved_count} in the fill-later queue
              {job.deferred_count ? ` (${job.deferred_count} deferred)` : ''}.
              {job.days_open != null ? ` Open ${job.days_open} day${job.days_open === 1 ? '' : 's'}.` : ''}
            </p>
            {canWrite && job.status === 'open' && !closeWarning && (
              <div className="actions">
                <button type="button" disabled={closeMut.isPending} onClick={() => closeMut.mutate(false)}>Close job</button>
              </div>
            )}
            {canWrite && closeWarning && (
              <div className="banner" role="alert">
                <p>{closeWarning.message}</p>
                <div className="actions">
                  <button type="button" onClick={() => setCloseWarning(null)}>Keep working</button>
                  <button type="button" className="primary" disabled={closeMut.isPending} onClick={() => closeMut.mutate(true)}>
                    Close anyway
                  </button>
                </div>
              </div>
            )}
            {canWrite && job.status === 'closed' && (
              <div className="actions">
                <button type="button" className="primary" disabled={reopenMut.isPending} onClick={() => reopenMut.mutate()}>Reopen</button>
              </div>
            )}
          </div>

          <div className="card">
            <h2>Fill-later queue</h2>
            {localWrites && (
              <p className="hint job-local-note" role="note">
                Completing items is saved only in this browser until the API ships open-item writes.
              </p>
            )}
            <div className="job-queue-filters" role="tablist" aria-label="Queue filter">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  role="tab"
                  aria-selected={filter === f.id}
                  className={filter === f.id ? 'primary' : undefined}
                  onClick={() => setFilter(f.id)}
                >
                  {f.label}
                </button>
              ))}
            </div>
            {itemsQuery.isLoading && <p className="hint">Loading items…</p>}
            {itemsQuery.error && <p className="error" role="alert">{itemsQuery.error instanceof Error ? itemsQuery.error.message : 'Failed to load items.'}</p>}
            {itemsQuery.isSuccess && items.length === 0 && <p className="hint">No items in this filter.</p>}
            {groups.map(([type, group]) => (
              <section key={type} className="job-queue-group" role="region" aria-label={humanizeItemType(type)}>
                <h3>{humanizeItemType(type)} <span className="job-badge">{group.length}</span></h3>
                <ul className="job-intake-queue">
                  {group.map((item) => (
                    <li key={item.id} className="job-queue-item">
                      <p>
                        {item.hostname && <span className="mono">{item.hostname}</span>}
                        {item.hostname && item.filename ? ' · ' : ''}
                        {item.filename}
                        {!item.hostname && !item.filename ? humanizeItemType(item.item_type) : null}
                        {item.target_field ? ` · ${item.target_field}` : ''}
                        {item.cable_label ? ` · ${item.cable_label}` : ''}
                        <span className="job-badge">{item.status}</span>
                      </p>
                      {item.status === 'deferred' && (
                        <p className="hint">Held by {item.deferred_by ?? 'someone'}{item.deferred_at ? ` · ${item.deferred_at}` : ''}</p>
                      )}
                      {item.note && <p className="hint">{item.note}</p>}
                      {canTrack && (item.status === 'open' || item.status === 'deferred') && (
                        <div className="actions">
                          <button type="button" onClick={() => void runItem(() => jobIntakeApi().resolveItem(item.job_id, item.id))}>Complete</button>
                          {item.status === 'open' && (
                            <button type="button" onClick={() => void runItem(() => jobIntakeApi().deferItem(item.job_id, item.id))}>Hold for later</button>
                          )}
                          {item.status === 'deferred' && (
                            <button type="button" onClick={() => void runItem(() => jobIntakeApi().undeferItem(item.job_id, item.id))}>Un-defer</button>
                          )}
                          <button type="button" onClick={() => { setDismissFor(item.id); setDismissNote('') }}>Dismiss</button>
                        </div>
                      )}
                      {dismissFor === item.id && (
                        <label className="field">
                          Dismiss note
                          <input value={dismissNote} onChange={(e) => setDismissNote(e.target.value)} aria-label="Dismiss note" />
                          <div className="actions">
                            <button type="button" onClick={() => setDismissFor(null)}>Cancel</button>
                            <button
                              type="button"
                              className="primary"
                              disabled={!dismissNote.trim()}
                              onClick={() => void runItem(async () => {
                                await jobIntakeApi().dismissItem(item.job_id, item.id, dismissNote.trim())
                                setDismissFor(null)
                              })}
                            >
                              Dismiss item
                            </button>
                          </div>
                        </label>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  )
}

