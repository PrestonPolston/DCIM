import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { noteFieldError } from '../api/errors'
import {
  JOB_INTAKE_API,
  closeOpenItemsWarning,
  countLabel,
  cableTrail,
  devicePageHref,
  fieldLabel,
  isJobHasOpenItems,
  isJobOverdue,
  itemTypeLabel,
  jobIntakeApi,
  jobItemWritesAvailable,
  type CloseWarning,
  type JobOpenItem,
  type OpenItemListStatus,
  type OpenItemWriteResult,
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

const WRITES_PENDING_NOTE = 'Complete, Fill, Hold and Dismiss arrive with the next API update.'

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
  const [params] = useSearchParams()
  const justCreated = params.get('created') === '1'
  const canWrite = useCan('job.write')
  const writesAvailable = jobItemWritesAvailable()
  const canAct = canWrite && writesAvailable
  const qc = useQueryClient()
  const [filter, setFilter] = useState<OpenItemListStatus>('unresolved')
  const [closeWarning, setCloseWarning] = useState<CloseWarning | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dismissFor, setDismissFor] = useState<number | null>(null)
  const [dismissNote, setDismissNote] = useState('')
  const [fillFor, setFillFor] = useState<number | null>(null)
  const [fillValue, setFillValue] = useState('')
  const [noteError, setNoteError] = useState<string | null>(null)

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

  async function invalidate() {
    await qc.invalidateQueries({ queryKey: ['jobs'] })
  }

  const closeMut = useMutation({
    mutationFn: (acknowledge: boolean) => jobIntakeApi().closeJob(job!.id, { acknowledge_open_items: acknowledge }),
    onSuccess: (result) => {
      setCloseWarning(null)
      setError(null)
      void qc.setQueryData(['jobs', idOrDcreq], result.job)
      void invalidate()
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
      void invalidate()
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Reopen failed.'),
  })

  async function runItem(op: () => Promise<OpenItemWriteResult | JobOpenItem>) {
    setError(null)
    setNoteError(null)
    try {
      const res = await op()
      const next = res && typeof res === 'object' && 'job' in res ? (res as OpenItemWriteResult).job : undefined
      if (next) {
        void qc.setQueryData(['jobs', idOrDcreq], next)
        void qc.setQueryData(['jobs', next.dcreq], next)
        void qc.setQueryData(['jobs', String(next.id)], next)
      }
      setDismissFor(null)
      setFillFor(null)
      setFillValue('')
      setDismissNote('')
      await invalidate()
    } catch (e) {
      const inline = noteFieldError(e)
      if (inline) setNoteError(inline)
      else setError(e instanceof Error ? e.message : 'That change could not be saved.')
    }
  }

  const jobErr = jobQuery.error instanceof ApiError ? jobQuery.error.message : jobQuery.error instanceof Error ? jobQuery.error.message : null
  const overdueFlag = job ? (job.overdue || isJobOverdue(job)) : false
  const unresolvedCount = job?.unresolved_count ?? 0

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
      {job && justCreated && (
        <div className="banner" role="status" aria-label="Job created">
          <p>This job was created, and the ePIF and cable-matrix items are waiting in its fill-later queue.</p>
        </div>
      )}
      {job && (
        <>
          <div className="card">
            <p role="status">
              {job.name} · {job.status}
              {overdueFlag && <span className="job-overdue">Open more than 30 days</span>}
            </p>
            <p className="hint" data-testid="job-queue-summary">
              {countLabel(job.device_count, 'device')} · {countLabel(job.connection_count ?? 0, 'connection')} · {unresolvedCount} in the fill-later queue
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
                <p className="user-text">{closeWarning.message}</p>
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
            {canWrite && !writesAvailable && (
              <p className="hint job-local-note" role="note">
                {WRITES_PENDING_NOTE}
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
              <section key={type} className="job-queue-group" role="region" aria-label={itemTypeLabel(type)}>
                <h3>{itemTypeLabel(type)} <span className="job-badge">{group.length}</span></h3>
                <ul className="job-intake-queue">
                  {group.map((item) => (
                    <li key={item.id} className="job-queue-item">
                      <p>
                        {item.hostname && <span className="mono">{item.hostname}</span>}
                        {item.hostname && item.filename ? ' · ' : ''}
                        {item.filename}
                        {!item.hostname && !item.filename ? itemTypeLabel(item.item_type) : null}
                        {item.target_field ? ` · ${fieldLabel(item.target_field)}` : ''}
                        {item.cable_label ? ` · ${item.cable_label}` : ''}
                        {cableTrail(item) ? ` · ${cableTrail(item)}` : ''}
                        <span className="job-badge">{item.status}</span>
                      </p>
                      {item.status === 'deferred' && (
                        <p className="hint">Held by {item.deferred_by ?? 'someone'}{item.deferred_at ? ` · ${item.deferred_at}` : ''}</p>
                      )}
                      {item.note && <p className="hint job-item-note">{item.note}</p>}
                      {item.filled_value && item.target_field && (
                        <p className="hint user-text">{fieldLabel(item.target_field)} set to {item.filled_value}</p>
                      )}
                      {canWrite && (item.status === 'open' || item.status === 'deferred') && (
                        <div className="actions">
                          <button
                            type="button"
                            disabled={!canAct}
                            onClick={() => void runItem(() => jobIntakeApi().resolveItem(item.job_id, item.id))}
                          >
                            Complete
                          </button>
                          <button
                            type="button"
                            disabled={!canAct}
                            onClick={() => { if (canAct) { setFillFor(item.id); setFillValue(''); setDismissFor(null); setNoteError(null) } }}
                          >
                            {JOB_INTAKE_API.live ? 'Resolve with note' : 'Fill'}
                          </button>
                          {item.status === 'open' && (
                            <button
                              type="button"
                              disabled={!canAct}
                              onClick={() => void runItem(() => jobIntakeApi().deferItem(item.job_id, item.id))}
                            >
                              Hold
                            </button>
                          )}
                          {item.status === 'deferred' && (
                            <button
                              type="button"
                              disabled={!canAct}
                              onClick={() => void runItem(() => jobIntakeApi().undeferItem(item.job_id, item.id))}
                            >
                              Un-defer
                            </button>
                          )}
                          <button
                            type="button"
                            disabled={!canAct}
                            onClick={() => { if (canAct) { setDismissFor(item.id); setDismissNote(''); setFillFor(null); setNoteError(null) } }}
                          >
                            Dismiss
                          </button>
                        </div>
                      )}
                      {canWrite && (item.status === 'open' || item.status === 'deferred') && item.target_field && (
                        <p className="hint" role="note">
                          Complete marks this resolved. It doesn't write {fieldLabel(item.target_field)}.
                        </p>
                      )}
                      {canAct && fillFor === item.id && (
                        JOB_INTAKE_API.live ? (
                          <div className="field">
                            <p className="hint" role="note" aria-label="Resolve with note">
                              This marks the item resolved and keeps your note.
                              {item.target_field ? (
                                <>
                                  {' '}It doesn't change {item.hostname ? <span className="mono">{item.hostname}</span> : 'this device'}; set {fieldLabel(item.target_field)} on{' '}
                                  {devicePageHref(item) ? <Link to={devicePageHref(item)!}>the device page</Link> : 'the device page'}.
                                </>
                              ) : null}
                            </p>
                            <label className="field">
                              Note
                              <textarea
                                value={fillValue}
                                onChange={(e) => { setFillValue(e.target.value); setNoteError(null) }}
                                aria-label="Note"
                                aria-invalid={noteError ? true : undefined}
                                rows={3}
                              />
                            </label>
                            {noteError && <p className="field-error" role="alert">{noteError}</p>}
                            <div className="actions">
                              <button type="button" onClick={() => setFillFor(null)}>Cancel</button>
                              <button
                                type="button"
                                className="primary"
                                disabled={!fillValue.trim()}
                                onClick={() => void runItem(() => jobIntakeApi().fillItem(item.job_id, item.id, fillValue.trim()))}
                              >
                                Save and resolve
                              </button>
                            </div>
                          </div>
                        ) : (
                          <label className="field">
                            {item.target_field ? `Value for ${item.target_field}` : 'Value'}
                            <input
                              value={fillValue}
                              onChange={(e) => setFillValue(e.target.value)}
                              aria-label={item.target_field ? `Value for ${item.target_field}` : 'Value'}
                            />
                            <div className="actions">
                              <button type="button" onClick={() => setFillFor(null)}>Cancel</button>
                              <button
                                type="button"
                                className="primary"
                                disabled={!fillValue.trim()}
                                onClick={() => void runItem(() => jobIntakeApi().fillItem(item.job_id, item.id, fillValue.trim()))}
                              >
                                Save and resolve
                              </button>
                            </div>
                          </label>
                        )
                      )}
                      {canAct && dismissFor === item.id && (
                        <label className="field">
                          Dismiss note
                          <input
                            value={dismissNote}
                            onChange={(e) => { setDismissNote(e.target.value); setNoteError(null) }}
                            aria-label="Dismiss note"
                            aria-invalid={noteError ? true : undefined}
                          />
                          {noteError && <p className="field-error" role="alert">{noteError}</p>}
                          <div className="actions">
                            <button type="button" onClick={() => setDismissFor(null)}>Cancel</button>
                            <button
                              type="button"
                              className="primary"
                              disabled={!dismissNote.trim()}
                              onClick={() => void runItem(() => jobIntakeApi().dismissItem(item.job_id, item.id, dismissNote.trim()))}
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
