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
