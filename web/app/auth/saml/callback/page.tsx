'use client'
import { useEffect, useRef, useState } from 'react';
import { AuthCallbackState } from '@/components/auth-callback-state';
import { useRouter } from '@/i18n/navigation';
import { setAuthSession } from '@/lib/auth-storage';
import { consumeSamlBridgeState, getSamlCallbackErrorMessage } from '@/lib/saml-session';

export default function SamlCallbackPage() {
  const router = useRouter()
  const ranRef = useRef(false)

  const [status, setStatus] = useState<'working' | 'success' | 'error'>('working')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    const routedError = new URLSearchParams(window.location.search).get('error')?.trim()
    if (routedError) {
      setStatus('error')
      setError(getSamlCallbackErrorMessage(routedError))
      return
    }

    void (async () => {
      const bridgeState = await consumeSamlBridgeState()
      if (!bridgeState) {
        setStatus('error')
        setError('登录会话已失效，请返回登录页重新发起登录。')
        return
      }

      if (bridgeState.kind === 'error') {
        setStatus('error')
        setError(getSamlCallbackErrorMessage(bridgeState.error))
        return
      }

      setAuthSession(bridgeState.session)
      setStatus('success')
      router.replace(bridgeState.returnTo || '/')
    })()
  }, [router])

  return <AuthCallbackState status={status} error={error ? error.startsWith('登录会话') ? error : '请返回登录页，重新发起单点登录。' : null} detail={error} onBack={() => router.replace('/auth')} />
}
