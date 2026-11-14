'use client'

import { useQuery } from '@tanstack/react-query'

import { metaApi } from '@/lib/api/meta'
import type { MetaDetailsResponse, MetaResponse } from '@/types/backend'

export function useBackendMeta() {
  return useQuery<MetaResponse>({
    queryKey: ['backend-meta'],
    queryFn: () => metaApi.get(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

export function useBackendMetaDetails() {
  return useQuery<MetaDetailsResponse>({
    queryKey: ['backend-meta-details'],
    queryFn: () => metaApi.details(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
