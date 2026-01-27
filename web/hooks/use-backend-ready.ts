'use client'

import { useQuery } from '@tanstack/react-query'

import { healthApi, type ReadyResponse } from '@/lib/api-client'

export function useBackendReady() {
  return useQuery<ReadyResponse>({
    queryKey: ['backend-ready'],
    queryFn: () => healthApi.ready(),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

