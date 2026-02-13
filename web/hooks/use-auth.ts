'use client'

import { useCallback, useEffect, useState } from 'react'
import type { UserProfile } from '@/types'
import { authApi } from '@/lib/api-client'
import { clearAuthSession, getAccessToken, getStoredUser, setStoredUser } from '@/lib/auth-storage'

export function useAuth() {
  const [user, setUser] = useState<UserProfile | null>(getStoredUser())
  const [isLoading, setIsLoading] = useState(false)

  const refresh = useCallback(async () => {
    const token = getAccessToken()
    if (!token) {
      setUser(getStoredUser())
      return
    }
    setIsLoading(true)
    try {
      const profile = await authApi.me()
      setStoredUser(profile)
      setUser(profile)
    } catch {
      clearAuthSession()
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    // Best-effort: clear server-side OIDC refresh token cookie if present.
    try {
      fetch('/api/oidc/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).catch(() => null)
    } catch {
      // ignore
    }
    clearAuthSession()
    setUser(null)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const isAuthenticated = Boolean(getAccessToken())
  const isDevMode = !isAuthenticated

  return {
    user,
    isLoading,
    isAuthenticated,
    isDevMode,
    refresh,
    logout,
  }
}
