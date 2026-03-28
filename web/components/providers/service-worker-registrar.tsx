'use client'

import { useEffect } from 'react'

type RegistrationEnv = {
  hasWindow: boolean
  hasServiceWorker: boolean
  hostname: string
  protocol?: string
  isSecureContext?: boolean
}

export function shouldRegisterServiceWorker(env: RegistrationEnv): boolean {
  if (!env.hasWindow || !env.hasServiceWorker) return false
  const hostname = String(env.hostname || '')
    .trim()
    .toLowerCase()
    .replace(/^\[(.*)\]$/, '$1')
  if (!hostname) return false
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') return false
  const protocol = String(env.protocol || '').trim().toLowerCase()
  if (protocol && protocol !== 'https:') return false
  if (env.isSecureContext === false) return false
  return true
}

export function ServiceWorkerRegistrar() {
  useEffect(() => {
    const enabled = shouldRegisterServiceWorker({
      hasWindow: typeof window !== 'undefined',
      hasServiceWorker: typeof navigator !== 'undefined' && 'serviceWorker' in navigator,
      hostname: globalThis.window?.location?.hostname || '',
      protocol: globalThis.window?.location?.protocol || '',
      isSecureContext: globalThis.window?.isSecureContext,
    })
    if (!enabled) return

    navigator.serviceWorker.register('/sw.js').catch((error) => {
      console.warn('Service worker registration failed', error)
    })
  }, [])

  return null
}
