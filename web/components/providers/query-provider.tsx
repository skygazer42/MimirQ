'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'

function getHttpStatus(error: unknown): number | null {
  const err = error as { response?: { status?: unknown }; status?: unknown }
  const status = err?.response?.status ?? err?.status
  return typeof status === 'number' ? status : null
}

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  // Avoid retry storms for bad requests, auth issues, etc.
  // Retry a couple of times for transient network/server failures.
  if (failureCount >= 2) return false

  const status = getHttpStatus(error)
  if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    return false
  }
  return true
}

export function QueryProvider({ children }: Readonly<{ children: React.ReactNode }>) {
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
      })
  )

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
