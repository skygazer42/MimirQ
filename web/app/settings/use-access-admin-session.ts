'use client'

import { useSyncExternalStore } from 'react'

import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'

export function useAccessAdminSession(): string {
  return useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
}
