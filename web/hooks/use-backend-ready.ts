'use client'

import { useQuery } from '@tanstack/react-query'

import { healthApi } from '@/lib/api'
import type { HealthDetailsResponse } from '@/types/backend'

export function useBackendReady() {
  return useQuery<HealthDetailsResponse>({
    queryKey: ['backend-health-details'],
    queryFn: () => healthApi.details(),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
