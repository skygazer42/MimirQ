'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { extractHttpStatus } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  // Avoid retry storms for bad requests, auth issues, etc.
  // Retry a couple of times for transient network/server failures.
  if (failureCount >= 2) return false

  const status = extractHttpStatus(error)
  if (status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    return false
  }
  return true
}

export function QueryProvider({ children }: Readonly<{ children: ReactNode }>) {
  const sessionKeyRef = useRef(getAuthSessionKey())
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            gcTime: 15 * 60_000,
            refetchOnWindowFocus: false,
            refetchOnReconnect: true,
            retry: shouldRetryQuery,
            retryDelay: (attemptIndex) => Math.min(1_000 * 2 ** attemptIndex, 10_000),
          },
          mutations: {
            retry: 0,
          },
        },
      }),
  )

  useEffect(() => {
    const clearChangedSession = () => {
      const sessionKey = getAuthSessionKey()
      if (sessionKeyRef.current === sessionKey) return
      sessionKeyRef.current = sessionKey
      queryClient.clear()
    }
    const unsubscribe = subscribeAuthSession(clearChangedSession)
    clearChangedSession()
    return unsubscribe
  }, [queryClient])

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
