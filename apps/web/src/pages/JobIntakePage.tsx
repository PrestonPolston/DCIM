import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  JOB_INTAKE_MAX_FILE_BYTES,
  duplicateExisting,
  isDuplicateDcreq,
  isValidDcreq,
  itemTypeLabel,
  jobHref,
  jobImportsAvailable,
  jobIntakeApi,
  normalizeDcreq,
  type IntakeCommitResult,
  type IntakePreview,
  type ImportKind,
  type Job,
  type JobImport,
} from '../api/jobIntake'
import type { ExistingJobRef } from '../api/errors'
import { useCan } from '../auth/auth'
import { errMessage } from '../api/home'


function itemLine(item: { hostname?: string | null; filename?: string | null; item_type: string; target_field?: string | null; status?: string }) {
  const lead = item.hostname ?? item.filename
  const type = itemTypeLabel(item.item_type)
  const bits = lead
    ? [<span key="h" className="mono">{lead}</span>, ` · ${type}`]
    : [type]
  if (item.target_field) bits.push(` · ${item.target_field}`)
  if (item.status) bits.push(` · ${item.status}`)
  return bits
}

const STEPS = ['DCREQ', 'ePIF', 'Cable matrix', 'Preview'] as const

function errText(e: unknown): string {
  return e instanceof Error ? e.message : errMessage(e)
}

function FileSlot({
  kind, label, current, skipped, disabled, uploadDisabled, onFile, onSkip, onClear, error,
}: {
  kind: ImportKind
  label: string
  current: JobImport | null
  skipped: boolean
  disabled: boolean
  uploadDisabled?: boolean
  onFile: (f: File) => void
  onSkip: () => void
  onClear: () => void
  error: string | null
}) {
  const fileBlocked = disabled || !!uploadDisabled
  return (
    <div className="job-intake-file">
      <h2>{label}</h2>
      {current ? (
        <p className="hint" role="status">
          {current.filename}: {current.counts.total} rows · {current.counts.ready} ready · {current.counts.warning} warning · {current.counts.held} held · {current.counts.conflict} conflict
        </p>
      ) : skipped ? (
        <p className="hint" role="status">Skipped. The {itemTypeLabel(kind === 'epif' ? 'epif_not_uploaded' : 'cable_matrix_not_uploaded')} item created with this job will stay open.</p>
      ) : (
        <p className="hint">.csv only, 8 MiB max. Skipping is allowed.</p>
      )}
      <label className="field">
        <span className="visually-hidden">{label} CSV</span>
        <input
          type="file"
          accept=".csv,text/csv"
          disabled={fileBlocked}
          aria-label={`${label} CSV`}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) onFile(f)
            e.target.value = ''
          }}
        />
      </label>
      <div className="actions">
        {!skipped && !current && <button type="button" disabled={disabled} onClick={onSkip}>Skip {kind === 'epif' ? 'ePIF' : 'cable matrix'}</button>}
        {(current || skipped) && <button type="button" disabled={disabled} onClick={onClear}>Use a different file</button>}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  )
}

export default function JobIntakePage() {
  const canWrite = useCan('job.write')
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [raw, setRaw] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [duplicate, setDuplicate] = useState<ExistingJobRef | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fileError, setFileError] = useState<{ epif: string | null; cable_matrix: string | null }>({ epif: null, cable_matrix: null })
  const [epif, setEpif] = useState<JobImport | null>(null)
  const [cable, setCable] = useState<JobImport | null>(null)
  const [skipped, setSkipped] = useState<{ epif: boolean; cable_matrix: boolean }>({ epif: false, cable_matrix: false })
  const [preview, setPreview] = useState<IntakePreview | null>(null)
  const [result, setResult] = useState<IntakeCommitResult | null>(null)
  const [leaveConfirm, setLeaveConfirm] = useState(false)
  const importsAvailable = jobImportsAvailable()

  const canonical = raw.trim() ? normalizeDcreq(raw) : ''
  const valid = isValidDcreq(raw)
  const showFormatHint = raw.trim().length > 0 && !valid

  function resetFromDcreqChange(value: string) {
    setRaw(value)
    setDuplicate(null)
    setError(null)
  }

  async function createJob() {
    if (!valid) return
    setBusy(true)
    setError(null)
    setDuplicate(null)
    try {
      const created = await jobIntakeApi().createJob(raw)
      setJob(created)
      setStep(1)
    } catch (e) {
      if (isDuplicateDcreq(e)) setDuplicate(duplicateExisting(e))
      else setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  function checkFile(file: File): string | null {
    if (!file.name.toLowerCase().endsWith('.csv')) return 'Upload a .csv file.'
    if (file.size > JOB_INTAKE_MAX_FILE_BYTES) return 'This file is larger than 8 MiB.'
    return null
  }

  async function upload(kind: ImportKind, file: File) {
    if (!job || !importsAvailable) return
    const problem = checkFile(file)
    setFileError((e) => ({ ...e, [kind]: problem }))
    if (problem) return
    setBusy(true)
    setError(null)
    try {
      const staged = await jobIntakeApi().stageImport(job.id, kind, file)
      if (kind === 'epif') { setEpif(staged); setSkipped((s) => ({ ...s, epif: false })) }
      else { setCable(staged); setSkipped((s) => ({ ...s, cable_matrix: false })) }
    } catch (e) {
      setFileError((err) => ({ ...err, [kind]: errText(e) }))
    } finally {
      setBusy(false)
    }
  }

  function skip(kind: ImportKind) {
    // No skip endpoint: the not-uploaded items were created with the job.
    if (kind === 'epif') { setEpif(null); setSkipped((s) => ({ ...s, epif: true })); setFileError((e) => ({ ...e, epif: null })) }
    else { setCable(null); setSkipped((s) => ({ ...s, cable_matrix: true })); setFileError((e) => ({ ...e, cable_matrix: null })) }
  }

  function clearFile(kind: ImportKind) {
    if (kind === 'epif') { setEpif(null); setSkipped((s) => ({ ...s, epif: false })) }
    else { setCable(null); setSkipped((s) => ({ ...s, cable_matrix: false })) }
    setFileError((e) => ({ ...e, [kind]: null }))
  }

  async function goPreview() {
    if (!job || !importsAvailable) return
    setBusy(true)
    setError(null)
    try {
      setPreview(await jobIntakeApi().previewJob(job.id))
      setStep(3)
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    if (!job || !importsAvailable) return
    setBusy(true)
    setError(null)
    try {
      setResult(await jobIntakeApi().commitIntake(job.id))
    } catch (e) {
      setError(errText(e))
    } finally {
      setBusy(false)
    }
  }

  function cancelIntake() {
    // DELETE/abandon is not in the committed API. After create, the job remains.
    if (!job) { navigate('/'); return }
    setLeaveConfirm(true)
  }

  function finishWithoutImport() {
    if (!job) return
    navigate(`${jobHref(job)}?created=1`)
  }

  function leaveBanner(created: Job) {
    if (!leaveConfirm) return null
    return (
      <div className="banner" role="status">
        <p>{created.dcreq} still exists as a job. Close it from the job page if you no longer need it.</p>
        <div className="actions">
          <Link className="button primary" to={jobHref(created)}>Open {created.dcreq}</Link>
          <Link className="button" to="/jobs">Back to jobs</Link>
          <button type="button" onClick={() => setLeaveConfirm(false)}>Keep working</button>
        </div>
      </div>
    )
  }

  function importUnavailableNote() {
    if (importsAvailable) return null
    return (
      <p className="banner" role="note">CSV import isn't available yet. You can finish now; the ePIF and cable-matrix items will wait in this job's fill-later queue.</p>
    )
  }

  const epifReady = !!epif || skipped.epif
  const cableReady = !!cable || skipped.cable_matrix
  const pending = preview?.pending_items ?? []

  function resetWizard() {
    setStep(0)
    setRaw('')
    setJob(null)
    setDuplicate(null)
    setBusy(false)
    setError(null)
    setFileError({ epif: null, cable_matrix: null })
    setEpif(null)
    setCable(null)
    setSkipped({ epif: false, cable_matrix: false })
    setPreview(null)
    setResult(null)
  }


  return (
    <section className="job-intake">
      <div className="page-header">
        <h1>{job ? `New job · ${job.dcreq}` : 'New job'}</h1>
      </div>
      <ol className="stepper" aria-label="Job intake steps">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? 'step' : undefined}>{i + 1}. {s}</li>
        ))}
      </ol>
      {!canWrite && <p className="banner" role="note">Starting a job needs the Technician or Admin role.</p>}

      {step === 0 && (
        <div className="card">
          <p>Job number = DCREQ</p>
          <label className="field">
            DCREQ
            <input
              type="text"
              className="mono"
              autoComplete="off"
              spellCheck={false}
              placeholder="DCREQ0001234"
              aria-describedby="dcreq-hint"
              aria-invalid={showFormatHint || !!duplicate || undefined}
              value={raw}
              disabled={!canWrite || busy}
              onChange={(e) => resetFromDcreqChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && valid && !duplicate && canWrite && !busy) void createJob() }}
            />
          </label>
          <p id="dcreq-hint" className="hint">
            {DCREQ_HINT(canonical, valid, showFormatHint)}
          </p>
          {showFormatHint && (
            <p className="field-error" role="alert">Enter a DCREQ like DCREQ0001234 (DCREQ000 + 4 digits).</p>
          )}
          {duplicate && (
            <div className="banner job-intake-duplicate" role="alert">
              <p><strong>{duplicate.dcreq}</strong> is already a job ({duplicate.name}, {duplicate.status}). Attaching more work to that job isn’t available yet.</p>
              <div className="actions">
                <Link className="button" to={jobHref(duplicate)}>Open that job</Link>
                <button type="button" onClick={() => { setRaw(''); setDuplicate(null) }}>Use a different DCREQ</button>
              </div>
            </div>
          )}
          {error && <p className="error" role="alert">{error}</p>}
          <div className="actions">
            <button type="button" onClick={() => navigate('/')}>Cancel</button>
            <button type="button" className="primary" disabled={!canWrite || !valid || !!duplicate || busy} onClick={() => void createJob()}>
              Next: ePIF
            </button>
          </div>
        </div>
      )}

      {step === 1 && job && (
        <div className="card">
          {importUnavailableNote()}
          {leaveBanner(job)}
          <FileSlot
            kind="epif"
            label="Space & Power (ePIF)"
            current={epif}
            skipped={skipped.epif}
            disabled={!canWrite || busy}
            uploadDisabled={!importsAvailable}
            onFile={(f) => void upload('epif', f)}
            onSkip={() => skip('epif')}
            onClear={() => clearFile('epif')}
            error={fileError.epif}
          />
          {error && <p className="error" role="alert">{error}</p>}
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => cancelIntake()}>Cancel intake</button>
            {importsAvailable ? (
              <button type="button" className="primary" disabled={!canWrite || !epifReady || busy} onClick={() => setStep(2)}>
                Next: Cable matrix
              </button>
            ) : (
              <>
                <button type="button" disabled={!canWrite || busy} onClick={() => setStep(2)}>
                  Next: Cable matrix
                </button>
                <button type="button" className="primary" disabled={!canWrite || busy} onClick={finishWithoutImport}>
                  Finish
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {step === 2 && job && (
        <div className="card">
          {importUnavailableNote()}
          {leaveBanner(job)}
          <FileSlot
            kind="cable_matrix"
            label="Cable matrix"
            current={cable}
            skipped={skipped.cable_matrix}
            disabled={!canWrite || busy}
            uploadDisabled={!importsAvailable}
            onFile={(f) => void upload('cable_matrix', f)}
            onSkip={() => skip('cable_matrix')}
            onClear={() => clearFile('cable_matrix')}
            error={fileError.cable_matrix}
          />
          {error && <p className="error" role="alert">{error}</p>}
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => cancelIntake()}>Cancel intake</button>
            <button type="button" disabled={busy} onClick={() => setStep(1)}>Back</button>
            {importsAvailable ? (
              <button type="button" className="primary" disabled={!canWrite || !cableReady || busy} onClick={() => void goPreview()}>
                Next: Preview
              </button>
            ) : (
              <button type="button" className="primary" disabled={!canWrite || busy} onClick={finishWithoutImport}>
                Finish
              </button>
            )}
          </div>
        </div>
      )}

      {step === 3 && job && !result && (
        <div className="card">
          {leaveBanner(job)}
          <h2>Preview{preview ? ` · ${job.dcreq}` : ''}</h2>
          {preview && (
            <>
              <p role="status">
                ePIF {preview.epif ? `${preview.epif.counts.total} rows: ${preview.epif.counts.ready} ready, ${preview.epif.counts.warning} warning, ${preview.epif.counts.held} held, ${preview.epif.counts.conflict} conflict` : (preview.skipped.epif ? 'skipped' : 'none')}
              </p>
              <p role="status">
                Cable {preview.cable_matrix ? `${preview.cable_matrix.counts.total} rows: ${preview.cable_matrix.counts.ready} ready, ${preview.cable_matrix.counts.warning} warning, ${preview.cable_matrix.counts.held} held, ${preview.cable_matrix.counts.conflict} conflict` : (preview.skipped.cable_matrix ? 'skipped' : 'none')}
              </p>
              <h3>Items that will stay in the fill-later queue ({pending.length})</h3>
              {pending.length === 0 ? <p className="hint">Nothing will be queued.</p> : (
                <ul className="job-intake-queue" aria-label="Pending fill-later items">
                  {pending.map((item, i) => (
                    <li key={`${item.item_type}-${item.import_row_id ?? i}`}>{itemLine(item)}</li>
                  ))}
                </ul>
              )}
            </>
          )}
          {error && <p className="error" role="alert">{error}</p>}
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => cancelIntake()}>Cancel intake</button>
            <button type="button" disabled={busy} onClick={() => { setResult(null); setStep(2) }}>Back</button>
            <button type="button" className="primary" disabled={!canWrite || !preview || busy} onClick={() => void commit()}>
              Commit job{pending.length ? ` — ${pending.length} stay in queue` : ''}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="card" aria-label="Import result" role="region">
          <h2>Import result · {result.job.dcreq}</h2>
          <p role="status">
            Job is {result.job.status}. {result.job.device_count} devices · {result.job.connection_count ?? 0} connections · {result.open_item_count} in the fill-later queue.
          </p>

          <h3>Warnings</h3>
          {result.warnings.length === 0 ? <p className="hint">No warnings.</p> : (
            <ul>
              {result.warnings.map((w, i) => (
                <li key={`${w.code}-${w.row_number ?? i}`}>
                  {w.hostname ? <span className="mono">{w.hostname}</span> : null}
                  {w.hostname ? ' · ' : ''}{w.message}{w.item_type ? ` (${w.item_type})` : ''}
                </li>
              ))}
            </ul>
          )}

          <h3>Skipped conflict rows</h3>
          {result.skipped_conflicts.length === 0 ? <p className="hint">No conflict rows were skipped.</p> : (
            <table className="table" aria-label="Skipped conflict rows">
              <thead><tr><th>File</th><th>Row</th><th>Hostname</th><th>Reason</th></tr></thead>
              <tbody>
                {result.skipped_conflicts.map((row) => (
                  <tr key={`${row.import_id}-${row.row_number}`}>
                    <td>{row.kind}</td>
                    <td>{row.row_number}</td>
                    <td className="mono">{row.hostname ?? '—'}</td>
                    <td>{row.messages.map((m) => m.message).join('; ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3>Fill-later queue</h3>
          {result.items.filter((i) => i.status === 'open' || i.status === 'deferred').length === 0 ? (
            <p className="hint">The queue is empty.</p>
          ) : (
            <ul className="job-intake-queue" aria-label="Fill-later queue">
              {result.items.filter((i) => i.status === 'open' || i.status === 'deferred').map((item) => (
                <li key={item.id}>{itemLine(item)}</li>
              ))}
            </ul>
          )}

          <div className="actions">
            <Link className="button primary" to={jobHref(result.job)}>Open job</Link>
            <button type="button" onClick={resetWizard}>Start another job</button>
          </div>
        </div>
      )}
    </section>
  )
}

function DCREQ_HINT(canonical: string, valid: boolean, showFormatHint: boolean): string {
  if (showFormatHint) return 'Hint: DCREQ000 + 4 digits. You can paste the full ID, 0001234, or 1234.'
  if (valid && canonical) return `Will be saved as ${canonical}.`
  return 'Hint: DCREQ000 + 4 digits. Paste the full ID, 0001234, or 1234.'
}
