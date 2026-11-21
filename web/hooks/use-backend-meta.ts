'use client'

import { useQuery } from '@tanstack/react-query'

import { metaApi } from '@/lib/api/meta'

export function useBackendMeta() {
  return useQuery({
    queryKey: ['backend-meta'],
    queryFn: ({ signal }) => metaApi.get({ signal }),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

export function useBackendMetaDetails() {
  return useQuery({
    queryKey: ['backend-meta-details'],
    queryFn: ({ signal }) => metaApi.details({ signal }),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
