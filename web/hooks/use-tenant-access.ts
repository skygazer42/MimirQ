'use client'

import { useQuery } from '@tanstack/react-query'

import { rbacApi } from '@/lib/api/access'
import { extractHttpStatus } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'

export function useTenantAccess(options: { enabled?: boolean } = {}) {
  const access = useQuery({
    queryKey: queryKeys.access.current,
    queryFn: ({ signal }) => rbacApi.getCurrentTenantAccess({ signal }),
    enabled: options.enabled,
    staleTime: 5 * 60_000,
    // A member may have just been promoted in another administrator's browser.
    refetchOnWindowFocus: 'always',
    retry: 1,
  })
  const status = extractHttpStatus(access.error)
  if (access.isRefetchError && (status === 401 || status === 403)) return { ...access, data: undefined }
  return access
}
