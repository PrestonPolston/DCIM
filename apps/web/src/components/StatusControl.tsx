import { useState } from 'react'
import { useUpdateDevice } from '../api/devices'
import { useCan } from '../auth/auth'
import { STATUSES, statusClass, statusIcon, statusLabel, statusTransition } from '../lib/status'
import ConfirmDialog from './ConfirmDialog'
import StatusBadge from './StatusBadge'

export interface StatusDevice {
  id: number
  host_name: string
  status: string
  needs_review?: boolean | null
  rack_id?: number | null
  position_u?: number | null
}

interface Props {
  device: StatusDevice
  /** Cabinet name for the Decom confirm copy. */
  rackName?: string | null
}

/**
 * 3-segment Install | Active | Decom control (mobile.md §4e). PATCH /devices/{id} {status}.
 * Decom (auto-unracks on the server) and recommissioning ask first. Read-only roles see a badge.
 */
export default function StatusControl({ device: d, rackName }: Props) {
  const canWrite = useCan('device.write')
  const update = useUpdateDevice()
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (!canWrite) return <StatusBadge status={d.status} />

  const flagged = !!d.needs_review
  async function apply(to: string) {
    const t = statusTransition(d.status, to)
    setError(null)
    try {
      await update.mutateAsync({ id: d.id, body: { status: to, ...(t.recommission ? { recommission: true } : {}) } })
      setPending(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }
  function pick(to: string) {
    const t = statusTransition(d.status, to)
    if (!t.ok) return
    if (to === 'decom' || t.recommission) setPending(to)
    else void apply(to)
  }
  const where = d.rack_id ? `${rackName ?? 'its cabinet'}${d.position_u ? ` (RU${d.position_u})` : ''}` : null

  return (
    <>
      <div className="segmented status-control" role="radiogroup" aria-label={`Status of ${d.host_name}`}>
        {STATUSES.map((s) => {
          const t = statusTransition(d.status, s)
          const current = d.status === s
          const blocked = flagged && s !== 'decom' && !current
          return (
            <button key={s} type="button" role="radio" aria-checked={current} aria-pressed={current}
              className={statusClass(s)} disabled={update.isPending || (!current && (!t.ok || blocked))}
              title={blocked ? 'Needs review: profile not published' : !current && !t.ok ? t.reason : undefined}
              onClick={() => !current && pick(s)}>
              <span aria-hidden="true">{statusIcon(s)}</span> {statusLabel(s)}
            </button>
          )
        })}
      </div>
      {error && !pending && <p className="error" role="alert">{error}</p>}
      {pending === 'decom' && (
        <ConfirmDialog title={`Decom ${d.host_name}?`} confirmLabel="Decom" danger busy={update.isPending} error={error}
          onCancel={() => { setPending(null); setError(null) }} onConfirm={() => void apply('decom')}>
          <p>
            {where ? <>It will be removed from {where} (unracked). </> : null}
            Its connections are kept and shown as Decom.
          </p>
        </ConfirmDialog>
      )}
      {pending && pending !== 'decom' && (
        <ConfirmDialog title={`Recommission ${d.host_name}?`} confirmLabel={statusLabel(pending)} busy={update.isPending} error={error}
          onCancel={() => { setPending(null); setError(null) }} onConfirm={() => void apply(pending)}>
          <p>It goes back to {statusLabel(pending)}, unplaced. Place it in a cabinet afterwards.</p>
        </ConfirmDialog>
      )}
    </>
  )
}
