import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, request, setCsrfToken } from '../api/client'
import type { AuthProvider, Me } from '../api/types'
import { can, type Action } from './permissions'

export const meKey = ['auth', 'me'] as const

export const authApi = {
  me: () => request<Me>('/auth/me'),
  login: (email: string, password: string) =>
    request<Me>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    request<Me>('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),
  providers: () => request<AuthProvider[]>('/auth/providers'),
}

/** Current user, or null when not signed in (401). Also refreshes the in-memory CSRF token. */
export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: async () => {
      try {
        const me = await authApi.me()
        setCsrfToken(me.csrf_token)
        return me
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setCsrfToken(null)
          return null
        }
        throw e
      }
    },
    staleTime: 60_000,
    retry: false,
  })
}

export function useCan(action: Action): boolean {
  return can(useMe().data?.role, action)
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => authApi.login(email, password),
    onSuccess: (me) => {
      setCsrfToken(me.csrf_token)
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
      qc.setQueryData(meKey, me)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => {
      setCsrfToken(null)
      qc.clear()
      qc.setQueryData(meKey, null)
    },
  })
}

export function useChangePassword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { current: string; next: string }) => authApi.changePassword(v.current, v.next),
    onSuccess: (me) => {
      setCsrfToken(me.csrf_token)
      qc.setQueryData(meKey, me)
    },
  })
}
