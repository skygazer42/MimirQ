'use client'
import { useEffect, useRef, useState } from 'react'
import { AuthCallbackState } from '@/components/auth-callback-state'
import { useRouter } from '@/i18n/navigation'
import { getAuthSessionRevision, setAuthSession } from '@/lib/auth-storage'
import { consumeSamlBridgeState, getSamlCallbackErrorMessage } from '@/lib/saml-session'

type SamlCallbackResult = { status: 'working' | 'success' } | { status: 'error'; message: string; detail?: string }

const LOGIN_AGAIN_MESSAGE = '请返回登录页，重新发起单点登录。'

export default function SamlCallbackPage() {
  const router = useRouter()
  const ranRef = useRef(false)
  const mountedRef = useRef(false)

  const [result, setResult] = useState<SamlCallbackResult>({ status: 'working' })

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    const routedError = new URLSearchParams(window.location.search).get('error')?.trim()
    if (routedError !== undefined && routedError !== '') {
      setResult({ status: 'error', message: LOGIN_AGAIN_MESSAGE, detail: getSamlCallbackErrorMessage(routedError) })
      return
    }

    const sessionRevision = getAuthSessionRevision()
    void (async () => {
      const bridgeState = await consumeSamlBridgeState()
      if (!mountedRef.current || getAuthSessionRevision() !== sessionRevision) return
      if (bridgeState === null) {
        setResult({ status: 'error', message: '登录会话已失效，请返回登录页重新发起登录。' })
        return
      }

      if (bridgeState.kind === 'error') {
        setResult({ status: 'error', message: LOGIN_AGAIN_MESSAGE, detail: bridgeState.error })
        return
      }

      setAuthSession(bridgeState.session)
      setResult({ status: 'success' })
      router.replace(bridgeState.returnTo)
    })()
  }, [router])

  return (
    <AuthCallbackState
      status={result.status}
      error={result.status === 'error' ? result.message : null}
      detail={result.status === 'error' ? result.detail : null}
      onBack={() => router.replace('/auth')}
    />
  )
}
