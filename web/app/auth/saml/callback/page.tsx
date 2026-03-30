'use client'

import { useEffect, useRef, useState } from 'react'
import { Loader2, ShieldAlert, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { useRouter } from '@/i18n/navigation'
import { setAuthSession } from '@/lib/auth-storage'
import { consumeSamlBridgeState } from '@/lib/saml-session'

export default function SamlCallbackPage() {
  const router = useRouter()
  const ranRef = useRef(false)

  const [status, setStatus] = useState<'working' | 'success' | 'error'>('working')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    const bridgeState = consumeSamlBridgeState()
    if (!bridgeState) {
      setStatus('error')
      setError('Missing SAML sign-in session.')
      return
    }

    if (bridgeState.kind === 'error') {
      setStatus('error')
      setError(bridgeState.error || 'SAML sign-in failed')
      return
    }

    setAuthSession(bridgeState.session)
    setStatus('success')
    router.replace(bridgeState.returnTo || '/')
  }, [router])

  return (
    <FullScreenFrame className="relative w-full overflow-hidden">
      <div className="relative z-10 w-full max-w-md p-6">
        <div className="rounded-3xl border border-border bg-card p-8 shadow-strong">
          {(() => {
    if (status === 'working') {
        return (<div className="flex items-start gap-3">
              <Loader2 className="mt-0.5 h-5 w-5 animate-spin motion-reduce:animate-none text-muted-foreground" aria-hidden="true"/>
              <div className="min-w-0 flex-1">
                <h1 className="text-base font-semibold text-foreground">Completing SAML sign-in</h1>
                <p className="mt-2 text-sm text-muted-foreground">Establishing your MimirQ session...</p>
              </div>
            </div>);
    }
    else if (status === 'success') {
            return (<div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 text-primary" aria-hidden="true"/>
              <div className="min-w-0 flex-1">
                <h1 className="text-base font-semibold text-foreground">Signed in</h1>
                <p className="mt-2 text-sm text-muted-foreground">Redirecting...</p>
              </div>
            </div>);
        }
        else {
            return (<div className="space-y-4">
              <div className="flex items-start gap-3">
                <ShieldAlert className="mt-0.5 h-5 w-5 text-destructive" aria-hidden="true"/>
                <div className="min-w-0 flex-1">
                  <h1 className="text-base font-semibold text-foreground">SAML sign-in failed</h1>
                  <p className="mt-2 break-words text-sm text-muted-foreground">{error || 'Please try again.'}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" onClick={() => router.replace('/auth')}>
                  Back to login
                </Button>
              </div>
            </div>);
        }
})()}
        </div>
      </div>
    </FullScreenFrame>
  )
}
