'use client'

import { useQuery } from '@tanstack/react-query'

import { healthApi } from '@/lib/api/health'

export function useBackendHealth(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['backend-health'],
    enabled: options?.enabled,
    queryFn: ({ signal }) => healthApi.details({ signal }),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
