import { MutationCache, QueryCache, QueryClient, type DefaultOptions } from '@tanstack/react-query'
import { ApiError } from './api/client'
import { meKey } from './auth/auth'

/** QueryClient that treats any 401 as "session ended": re-check /auth/me so RequireAuth redirects to login. */
export function createQueryClient(defaultOptions: DefaultOptions = {}) {
  const on401 = (err: unknown) => {
    if (err instanceof ApiError && err.status === 401) void qc.invalidateQueries({ queryKey: meKey })
  }
  const qc: QueryClient = new QueryClient({
    defaultOptions: {
      ...defaultOptions,
      queries: {
        ...defaultOptions.queries,
        retry: defaultOptions.queries?.retry === false ? false : (n, err) => !(err instanceof ApiError && [401, 403, 404].includes(err.status)) && n < 1,
      },
    },
    queryCache: new QueryCache({ onError: on401 }),
    mutationCache: new MutationCache({ onError: on401 }),
  })
  return qc
}
