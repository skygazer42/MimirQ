'use client'

import { useEffect } from 'react'

import { usePathname, useRouter } from '@/i18n/navigation'
import { getAccessToken } from '@/lib/auth-storage'
import { useBackendMeta } from '@/hooks/use-backend-meta'

export function AuthGuard({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter()
  const pathname = usePathname()
  const { data: meta } = useBackendMeta()

  useEffect(() => {
    const authMode = String(meta?.features?.auth_mode || '')
    if (!authMode) return

    // In dev/header mode, the backend accepts X-User-ID so no login is required.
    if (authMode !== 'jwt') return

    const token = getAccessToken()
    if (token) return

    if (pathname.startsWith('/auth')) return
    router.replace('/auth')
  }, [meta?.features?.auth_mode, pathname, router])

  return <>{children}</>
}
