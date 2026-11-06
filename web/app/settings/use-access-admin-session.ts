'use client'

import { useSyncExternalStore } from 'react'

import { AUTH_SCOPE_CHANGED_EVENT, getAuthSessionRevision } from '@/lib/auth-storage'

export function useAccessAdminSession(): number {
  return useSyncExternalStore(subscribeToSession, getAuthSessionRevision, () => 0)
}

function subscribeToSession(onChange: () => void): () => void {
  window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, onChange)
  return () => window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, onChange)
}
