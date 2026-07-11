'use client'

import { useQuery } from '@tanstack/react-query'

import { healthApi } from '@/lib/api'
import type { HealthDetailsResponse } from '@/types/backend'

export type BackendHealthSnapshot = {
  payload: HealthDetailsResponse
  latencyMs: number
}

export function useBackendHealth() {
  return useQuery<BackendHealthSnapshot>({
    queryKey: ['backend-health'],
    queryFn: async () => {
      const start = Date.now()
      const payload = await healthApi.details()
      const latencyMs = Math.max(0, Date.now() - start)
      return { payload, latencyMs }
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
