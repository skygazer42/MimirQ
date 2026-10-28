'use client'
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { AuthCallbackState } from '@/components/auth-callback-state';
import { useRouter } from '@/i18n/navigation';
import { completeOidcLogin } from '@/lib/oidc';

export default function OidcCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const ranRef = useRef(false)

  const [status, setStatus] = useState<'working' | 'success' | 'error'>('working')
  const [error, setError] = useState<string | null>(null)

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

    ;(async () => {
      try {
        const { returnTo } = await completeOidcLogin({ code, state })
        setStatus('success')
        router.replace(returnTo || '/')
      } catch (e: unknown) {
        setStatus('error')
        setError(e instanceof Error ? e.message : '单点登录失败，请重新登录。')
      }
    })()
  }, [router, searchParams])

  return <AuthCallbackState status={status} error={error} onBack={() => router.replace('/auth')} />
}
