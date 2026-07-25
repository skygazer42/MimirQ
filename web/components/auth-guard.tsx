'use client'

import { Fragment, useEffect, useState } from 'react'

import { usePathname, useRouter } from '@/i18n/navigation'
import { AUTH_SCOPE_CHANGED_EVENT, getAccessToken } from '@/lib/auth-storage'
import { useBackendMeta } from '@/hooks/use-backend-meta'

export function AuthGuard({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter()
  const pathname = usePathname()
  const { data: meta, isPending, isError } = useBackendMeta()
  const [authRevision, setAuthRevision] = useState(0)
  const authMode = String(meta?.features?.auth_mode || '').trim().toLowerCase()
  const isAuthRoute = pathname.startsWith('/auth')
  const authModeResolved = authMode === 'jwt' || authMode === 'header'
  const authRequired = authModeResolved && authMode === 'jwt'
  const hasAccessToken = Boolean(getAccessToken())
  const shouldBlockProtectedRoute =
    !isAuthRoute && (!authModeResolved || isError || (authRequired && !hasAccessToken))
  const shouldRedirectToAuth =
    !isAuthRoute && (
      isError ||
      (authModeResolved && authRequired && !hasAccessToken) ||
      (!authModeResolved && !isPending)
    )

  useEffect(() => {
    const recheckAuth = () => setAuthRevision((revision) => revision + 1)
    globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, recheckAuth)
    return () => {
      globalThis.window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, recheckAuth)
    }
  }, [])

  useEffect(() => {
    if (!shouldRedirectToAuth) return
    router.replace('/auth')
  }, [authRevision, router, shouldRedirectToAuth])

  if (shouldBlockProtectedRoute) return null

  return <Fragment key={authRevision}>{children}</Fragment>
}
