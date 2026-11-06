// TanStack Query hooks for devices. Components use these, not the raw client.
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { devicesApi } from './client'
import type { DeviceCreate, DeviceListParams, DeviceUpdate } from './types'

export const deviceKeys = {
  all: ['devices'] as const,
  list: (params: DeviceListParams) => [...deviceKeys.all, 'list', params] as const,
}

/** Server-side filtered/paginated device list ({ items, total }). */
export function useDevices(params: DeviceListParams = {}, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: deviceKeys.list(params),
    queryFn: () => devicesApi.list(params),
    placeholderData: keepPreviousData,
    enabled: opts.enabled ?? true,
  })
}

function invalidateDeviceViews(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: deviceKeys.all }),
    qc.invalidateQueries({ queryKey: ['elevation'] }),
    qc.invalidateQueries({ queryKey: ['hall-layout'] }),
  ])
}

export function useCreateDevice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: DeviceCreate) => devicesApi.create(body),
    onSuccess: () => invalidateDeviceViews(qc),
  })
}

export function useUpdateDevice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: DeviceUpdate }) => devicesApi.update(id, body),
    onSuccess: () => invalidateDeviceViews(qc),
  })
}

export function useDeleteDevice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => devicesApi.remove(id),
    onSuccess: () => invalidateDeviceViews(qc),
  })
}
