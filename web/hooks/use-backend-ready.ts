'use client'

import { useQuery } from '@tanstack/react-query'

import { healthApi } from '@/lib/api/health'

export function useBackendReady() {
  return useQuery({
    queryKey: ['backend-ready'],
    queryFn: ({ signal }) => healthApi.ready({ signal }),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
