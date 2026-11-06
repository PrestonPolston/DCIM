import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { useLogin, useMe } from '../auth/auth'
import { safeNext } from '../auth/next'

export default function LoginPage() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const me = useMe()
  const login = useLogin()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (me.data) return <Navigate to={next} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      await login.mutateAsync({ email: email.trim(), password })
      navigate(next, { replace: true })
    } catch {
      /* shown below */
    }
  }

  return (
    <main className="login">
      <form className="card form" onSubmit={submit} aria-label="Sign in">
        <h1>DCIM sign in</h1>
        <label className="field">
          Email
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {login.error && <p className="error" role="alert">{login.error.message}</p>}
        <div className="actions">
          <button type="submit" className="primary" disabled={login.isPending}>
            {login.isPending ? 'Signing in…' : 'Sign in'}
          </button>
        </div>
      </form>
    </main>
  )
}
