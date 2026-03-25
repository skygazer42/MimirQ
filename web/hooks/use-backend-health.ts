'use client'

import { useQuery } from '@tanstack/react-query'

import { healthApi } from '@/lib/api'
import type { HealthResponse } from '@/types/backend'

export type BackendHealthSnapshot = {
  payload: HealthResponse
  latencyMs: number
}

export function useBackendHealth() {
  return useQuery<BackendHealthSnapshot>({
    queryKey: ['backend-health'],
    queryFn: async () => {
      const start = Date.now()
      const payload = await healthApi.health()
      const latencyMs = Math.max(0, Date.now() - start)
      return { payload, latencyMs }
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

