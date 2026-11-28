'use client'

import { Fragment, useEffect, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'

import { usePathname, useRouter } from '@/i18n/navigation'
import { getAccessToken, getAuthSessionRevision, subscribeAuthSession } from '@/lib/auth-storage'
import { useBackendMeta } from '@/hooks/use-backend-meta'

type AuthGuardProps = {
  children: ReactNode
}

export function AuthGuard({ children }: Readonly<AuthGuardProps>) {
  const router = useRouter()
  const pathname = usePathname()
  const { data: meta, isPending, isError } = useBackendMeta()
  const authRevision = useSyncExternalStore(subscribeAuthSession, getAuthSessionRevision, () => 0)
  const authMode = meta?.features.auth_mode
  const isAuthRoute = pathname.startsWith('/auth')
  const authModeResolved = authMode === 'jwt' || authMode === 'header'
  const authRequired = authMode === 'jwt'
  const hasAccessToken = Boolean(getAccessToken())
  const shouldBlockProtectedRoute = !isAuthRoute && (!authModeResolved || isError || (authRequired && !hasAccessToken))
  const shouldRedirectToAuth =
    !isAuthRoute && (isError || (authRequired && !hasAccessToken) || (!authModeResolved && !isPending))

  useEffect(() => {
    if (!shouldRedirectToAuth) return
    router.replace('/auth')
  }, [authRevision, router, shouldRedirectToAuth])

  if (shouldBlockProtectedRoute) return null

  // Saving a successful login updates the auth scope before navigation finishes.
  // Keep that form mounted; only private pages need their state reset on account changes.
  return <Fragment key={isAuthRoute ? 'auth' : authRevision}>{children}</Fragment>
}
