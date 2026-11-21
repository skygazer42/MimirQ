'use client'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { AuthCallbackState } from '@/components/auth-callback-state'
import { useRouter } from '@/i18n/navigation'
import { completeOidcLogin } from '@/lib/oidc'
import { getAuthSessionRevision, setAuthSession } from '@/lib/auth-storage'

type CallbackResult = { status: 'working' | 'success'; error: null } | { status: 'error'; error: string }

export default function OidcCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const ranRef = useRef(false)
  const mountedRef = useRef(false)

  const [result, setResult] = useState<CallbackResult>({ status: 'working', error: null })

  useLayoutEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    const errorCode = searchParams.get('error')
    const errorDescription = searchParams.get('error_description')
    if (errorCode) {
      setResult({ status: 'error', error: errorDescription ? `${errorCode}: ${errorDescription}` : errorCode })
      return
    }

    const code = searchParams.get('code')
    const state = searchParams.get('state')
    if (!code || !state) {
      setResult({ status: 'error', error: '登录信息不完整，请返回登录页重新发起登录。' })
      return
    }

    const sessionRevision = getAuthSessionRevision()
    const canPublish = () => mountedRef.current && getAuthSessionRevision() === sessionRevision
    async function finishLogin(code: string, state: string) {
      try {
        const { session, returnTo } = await completeOidcLogin({ code, state })
        if (!canPublish()) return
        setAuthSession(session)
        setResult({ status: 'success', error: null })
        router.replace(returnTo)
      } catch (error) {
        if (!canPublish()) return
        setResult({
          status: 'error',
          error: error instanceof Error ? error.message : '单点登录失败，请重新登录。',
        })
      }
    }
    void finishLogin(code, state)
  }, [router, searchParams])

  return <AuthCallbackState {...result} onBack={() => router.replace('/auth')} />
}
