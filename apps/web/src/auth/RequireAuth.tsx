import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useMe } from './auth'

/** Redirects to /login (with ?next=) when signed out; forces a password change when required. */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isPending, error } = useMe()
  const loc = useLocation()
  const here = loc.pathname + loc.search
  if (isPending) return <p className="content">Loading…</p>
  if (error) return <p className="content error" role="alert">{error.message}</p>
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(here)}`} replace />
  if (me.must_change_password && loc.pathname !== '/account/password')
    return <Navigate to={`/account/password?next=${encodeURIComponent(here)}`} replace />
  return <>{children}</>
}
