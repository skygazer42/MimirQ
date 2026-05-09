'use client'

import { useQuery } from '@tanstack/react-query'

import { rbacApi } from '@/lib/api/access'
import { queryKeys } from '@/lib/query-keys'
import type { TenantAccess } from '@/lib/tenant-permissions'

export function useTenantAccess() {
  return useQuery<TenantAccess>({
    queryKey: queryKeys.access.current,
    queryFn: () => rbacApi.getCurrentTenantAccess(),
    staleTime: 5 * 60_000,
    retry: 1,
  })
}
