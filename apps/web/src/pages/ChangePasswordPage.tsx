import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import { useChangePassword, useMe } from '../auth/auth'
import { safeNext } from '../auth/next'

export default function ChangePasswordPage() {
  const me = useMe().data
  const change = useChangePassword()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (next !== confirm) return setError('New passwords do not match.')
    setError(null)
    try {
      await change.mutateAsync({ current, next })
      setDone(true)
      setCurrent(''); setNext(''); setConfirm('')
      if (params.get('next')) navigate(safeNext(params.get('next')), { replace: true })
    } catch (err) {
      const d = err instanceof ApiError ? (err.detail as { detail?: unknown })?.detail : undefined
      setError(Array.isArray(d) && d.every((x) => typeof x === 'string') ? d.join(' ') : err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <section>
      <form className="card form" onSubmit={submit} aria-label="Change password">
        <h2>Change password</h2>
        {me?.must_change_password && <p className="banner">You must set a new password before continuing.</p>}
        <label className="field">
          Current password
          <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label className="field">
          New password
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        </label>
        <label className="field">
          Confirm new password
          <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        {done && <p className="hint" role="status">Password changed. Other sessions were signed out.</p>}
        <div className="actions">
          <button type="submit" className="primary" disabled={change.isPending}>Change password</button>
        </div>
      </form>
    </section>
  )
}
