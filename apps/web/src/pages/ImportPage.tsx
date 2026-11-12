// CSV import (screens.md, profiles.md §9): Upload → Dry run → Import, over
// POST /devices/import?dry_run=. Column mapping isn't built (the API maps by header).
import { useState } from 'react'
import { Link } from 'react-router'
import { send } from '../api/client'
import { profileTitle, useProfiles } from '../api/profiles'
import { useCan } from '../auth/auth'
import { parseCsv } from '../lib/csv'
import { classifyRowError, rowModel } from '../lib/importErrors'

const STEPS = ['Upload', 'Dry run', 'Import']

interface ImportResult { dry_run: boolean; total_rows: number; created: number; errors: { row: number; errors: string[] }[]; errors_truncated?: boolean; warnings?: unknown[] }

async function runImport(text: string, dryRun: boolean): Promise<ImportResult> {
  const res = await send(`/devices/import?dry_run=${dryRun}`, { method: 'POST', body: text, headers: { 'Content-Type': 'text/csv' } })
  return (await res.json()) as ImportResult
}

export default function ImportPage() {
  const canImport = useCan('device.import')
  const canStartJob = useCan('job.write')
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [result, setResult] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const drafts = useProfiles({ status: 'draft' }).items
  const rows = text ? parseCsv(text) : []
  const headers = rows[0] ?? []
  const step = result ? (result.dry_run ? 1 : 2) : 0

  async function pick(f: File | undefined) {
    setFile(f ?? null); setResult(null); setError(null)
    setText(f ? await f.text() : '')
  }
  async function go(dryRun: boolean) {
    setBusy(true); setError(null)
    try { setResult(await runImport(text, dryRun)) } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  const profileRows = (result?.errors ?? []).filter((e) => e.errors.some((m) => classifyRowError(m) === 'profile_required'))
  const neededModels = new Map<string, { manufacturer: string; model: string }>()
  for (const e of profileRows) { const m = rowModel(rows, e.row); neededModels.set(`${m.manufacturer}|${m.model}`.toLowerCase(), m) }
  const draftFor = (m: { manufacturer: string; model: string }) =>
    drafts.find((d) => d.manufacturer.toLowerCase() === m.manufacturer.toLowerCase() && d.model.toLowerCase() === m.model.toLowerCase())

  return (
    <section>
      <div className="page-header"><h1>CSV import</h1></div>
      {canStartJob && (
        <p className="job-intake-entry">Starting a DCREQ job with an ePIF and cable matrix? <Link to="/jobs/new">New job</Link></p>
      )}
      <ol className="stepper" aria-label="Import steps">
        {STEPS.map((s, i) => <li key={s} aria-current={i === step ? 'step' : undefined}>{i + 1}. {s}</li>)}
      </ol>
      {!canImport && <p className="banner" role="note">CSV import needs the Technician or Admin role.</p>}
      <div className="card">
        <label className="field">
          CSV file
          <input type="file" accept=".csv,text/csv" disabled={!canImport} onChange={(e) => void pick(e.target.files?.[0])} />
        </label>
        {file && <p className="hint">{file.name}: columns {headers.join(', ') || '(none)'}</p>}
        <p className="hint">Rows that place a device (rack, rack_id or position_u) need a published profile: profile_id, or manufacturer + model. Unplaced rows need only host_name.</p>
        <div className="actions">
          <button type="button" className="primary" disabled={!text || busy || !canImport} onClick={() => void go(true)}>{result?.dry_run ? 'Re-run dry run' : 'Dry run'}</button>
          {result?.dry_run && result.errors.length === 0 && <button type="button" disabled={busy} onClick={() => void go(false)}>Import {result.total_rows} rows</button>}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </div>
      {result && (
        <div className="card" aria-label="Import result" role="region">
          <p role="status">
            {result.dry_run ? 'Dry run' : 'Imported'}: {result.total_rows} rows · {result.errors.length} with errors{result.dry_run ? '' : ` · ${result.created} created`}
            {result.errors_truncated ? ' (first errors only)' : ''}
          </p>
          {neededModels.size > 0 && (
            <p className="banner">
              {profileRows.length} row{profileRows.length === 1 ? '' : 's'} need {neededModels.size} profile{neededModels.size === 1 ? '' : 's'} that aren't published.
            </p>
          )}
          {result.errors.length > 0 && (
            <table className="table" aria-label="Row errors">
              <thead><tr><th>Line</th><th>Error</th><th><span className="visually-hidden">Fix</span></th></tr></thead>
              <tbody>
                {result.errors.map((e) => {
                  const isProfile = e.errors.some((m) => classifyRowError(m) === 'profile_required')
                  const m = rowModel(rows, e.row)
                  const draft = isProfile ? draftFor(m) : undefined
                  const q = new URLSearchParams({ new: '1', manufacturer: m.manufacturer, model: m.model })
                  return (
                    <tr key={e.row}>
                      <td className="mono">{e.row}</td>
                      <td>{isProfile && <span className="badge needs-profile">profile_required</span>} {e.errors.join('; ')}</td>
                      <td>
                        {isProfile && (draft
                          ? <Link to={`/profiles?status=draft&q=${encodeURIComponent(draft.model)}`}>Finish draft ({profileTitle(draft)} · {draft.name})</Link>
                          : <Link to={`/profiles?${q}`}>Create profile</Link>)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  )
}
