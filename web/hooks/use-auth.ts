'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useSyncExternalStore } from 'react'
import { authApi } from '@/lib/api/auth'
import { extractHttpStatus } from '@/lib/api-errors'
import {
  clearAuthSession,
  getAccessToken,
  getAuthSessionRevision,
  getStoredUser,
  setStoredUser,
  subscribeAuthSession,
} from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'

export function useAuth() {
  const queryClient = useQueryClient()
  useSyncExternalStore(subscribeAuthSession, getAuthSessionRevision, () => 0)
  const accessToken = getAccessToken()
  const initialUser = getStoredUser()

  const {
    data: user,
    error,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: queryKeys.auth.profile,
    queryFn: async ({ signal }) => {
      const token = getAccessToken()
      const sessionRevision = getAuthSessionRevision()
      if (!token) return getStoredUser()

      try {
        const profile = await authApi.me({ signal })
        if (signal.aborted || sessionRevision !== getAuthSessionRevision()) return getStoredUser()
        setStoredUser(profile)
        return profile
      } catch (err) {
        if (signal.aborted || sessionRevision !== getAuthSessionRevision()) return getStoredUser()
        if (extractHttpStatus(err) === 401) {
          if (getAccessToken() !== token) return getStoredUser()
          clearAuthSession()
          return null
        }
        throw err
      }
    },
    enabled: Boolean(accessToken),
    initialData: initialUser,
    staleTime: 5 * 60_000,
  })

  const refresh = useCallback(async () => {
    if (!getAccessToken()) {
      queryClient.setQueryData(queryKeys.auth.profile, getStoredUser())
      return
    }

    await refetch()
  }, [queryClient, refetch])

  const logout = useCallback(() => {
    // Best-effort: clear server-side OIDC refresh token cookie if present.
    void fetch('/api/oidc/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).catch(
      () => undefined,
    )
    clearAuthSession()
    queryClient.clear()
  }, [queryClient])

  const isAuthenticated = Boolean(accessToken)
  const isDevMode = !isAuthenticated

  return {
    user,
    error,
    isLoading: isFetching,
    isAuthenticated,
    isDevMode,
    refresh,
    logout,
  }
}
