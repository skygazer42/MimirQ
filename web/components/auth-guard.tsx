'use client'

import { Fragment, useEffect, useState } from 'react'

import { usePathname, useRouter } from '@/i18n/navigation'
import { AUTH_SCOPE_CHANGED_EVENT, getAccessToken } from '@/lib/auth-storage'
import { useBackendMeta } from '@/hooks/use-backend-meta'

export function AuthGuard({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter()
  const pathname = usePathname()
  const { data: meta } = useBackendMeta()
  const [authRevision, setAuthRevision] = useState(0)
  const authMode = String(meta?.features?.auth_mode || '')
  const authRequired = authMode === 'jwt'
  const hasAccessToken = Boolean(getAccessToken())

  useEffect(() => {
    const recheckAuth = () => setAuthRevision((revision) => revision + 1)
    globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, recheckAuth)
    return () => {
      globalThis.window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, recheckAuth)
    }
  }, [])

  useEffect(() => {
    if (!authRequired || hasAccessToken) return

    if (pathname.startsWith('/auth')) return
    router.replace('/auth')
  }, [authRequired, authRevision, hasAccessToken, pathname, router])

  if (authRequired && !hasAccessToken && !pathname.startsWith('/auth')) return null

  return <Fragment key={authRevision}>{children}</Fragment>
}
