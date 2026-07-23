'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import type { UserProfile } from '@/types'
import { authApi } from '@/lib/api/auth'
import { clearAuthSession, getAccessToken, getStoredUser, setStoredUser } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'

function getHttpStatus(error: unknown): number | null {
  const err = error as { response?: { status?: unknown }; status?: unknown }
  const status = err?.response?.status ?? err?.status
  return typeof status === 'number' ? status : null
}

export function useAuth() {
  const queryClient = useQueryClient()
  const accessToken = getAccessToken()
  const initialUser = getStoredUser()

  const { data: user, error, isFetching, refetch } = useQuery<UserProfile | null>({
    queryKey: queryKeys.auth.profile,
    queryFn: async () => {
      const token = getAccessToken()
      if (!token) return getStoredUser()

      try {
        const profile = await authApi.me()
        setStoredUser(profile)
        return profile
      } catch (err) {
        if (getHttpStatus(err) === 401) {
          if (getAccessToken()) {
            clearAuthSession()
          }
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
    void fetch('/api/oidc/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).catch(() => undefined)
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
