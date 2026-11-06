'use client'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { AuthCallbackState } from '@/components/auth-callback-state'
import { useRouter } from '@/i18n/navigation'
import { completeOidcLogin } from '@/lib/oidc'
import { getAuthSessionRevision, setAuthSession } from '@/lib/auth-storage'

export default function OidcCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const ranRef = useRef(false)
  const mountedRef = useRef(false)

  const [status, setStatus] = useState<'working' | 'success' | 'error'>('working')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    const errorCode = searchParams.get('error')
    const errorDesc = searchParams.get('error_description')
    if (errorCode) {
      setStatus('error')
      setError([errorCode, errorDesc].filter(Boolean).join(': ') || '单点登录失败，请重新登录。')
      return
    }

    const code = searchParams.get('code')
    const state = searchParams.get('state')
    if (!code || !state) {
      setStatus('error')
      setError('登录信息不完整，请返回登录页重新发起登录。')
      return
    }

    const sessionRevision = getAuthSessionRevision()
    const canPublish = () => mountedRef.current && getAuthSessionRevision() === sessionRevision
    ;(async () => {
      try {
        const { session, returnTo } = await completeOidcLogin({ code, state })
        if (!canPublish()) return
        setAuthSession(session)
        setStatus('success')
        router.replace(returnTo || '/')
      } catch (e: unknown) {
        if (!canPublish()) return
        setStatus('error')
        setError(e instanceof Error ? e.message : '单点登录失败，请重新登录。')
      }
    })()
  }, [router, searchParams])

  return <AuthCallbackState status={status} error={error} onBack={() => router.replace('/auth')} />
}
