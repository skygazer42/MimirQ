'use client'

import { RouteError } from '@/components/route-error'

export default function GlobalErrorPage({
  error,
  reset,
}: Readonly<{
  error: Error & { digest?: string }
  reset: () => void
}>) {
  return <RouteError error={error} reset={reset} fullScreen />
}
