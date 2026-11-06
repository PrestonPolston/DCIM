import type { ReactNode } from 'react'
import { render } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '../queryClient'
import { MemoryRouter } from 'react-router'

export function renderWithProviders(ui: ReactNode, path = '/') {
  const qc = createQueryClient({ queries: { retry: false } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}
