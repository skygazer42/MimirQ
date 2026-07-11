'use client'

import { useQuery } from '@tanstack/react-query'

import { metaApi, type BackendMeta, type BackendMetaDetails } from '@/lib/api'

export function useBackendMeta() {
  return useQuery<BackendMeta>({
    queryKey: ['backend-meta'],
    queryFn: () => metaApi.get(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

export function useBackendMetaDetails() {
  return useQuery<BackendMetaDetails>({
    queryKey: ['backend-meta-details'],
    queryFn: () => metaApi.details(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
