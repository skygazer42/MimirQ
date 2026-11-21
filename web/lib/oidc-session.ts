'use client'

import { authTokenSchema } from '@/lib/auth-response-schema'
import { getAccessToken, getAuthSessionKey } from '@/lib/auth-storage'
import { recordSchema } from '@/lib/response-schema'
import type { AuthToken } from '@/types/backend'

const OIDC_REFRESH_TERMINAL_ERRORS = new Set([
  'oidc_server_exchange_disabled',
  'oidc_not_configured',
  'oidc_provider_required',
])

let inFlight: {
  sessionKey: string
  token: string | null
  promise: Promise<AuthToken | null>
} | null = null

export function __resetOidcRefreshForTests() {
  inFlight = null
}

export function tryRefreshOidcAccessToken(): Promise<AuthToken | null> {
  const sessionKey = getAuthSessionKey()
  const token = getAccessToken()
  if (inFlight?.sessionKey === sessionKey && inFlight.token === token) {
    return inFlight.promise
  }

  const promise = (async () => {
    const response = await fetch('/api/oidc/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      cache: 'no-store',
    })
    if (response.status === 401) return null
    if (response.ok) return authTokenSchema.parse(await response.json())

    if (response.status === 400) {
      const result = recordSchema.safeParse(await response.json().catch(() => null))
      if (result.success) {
        const { code, error } = result.data
        if (code === 'invalid_grant' || (typeof error === 'string' && OIDC_REFRESH_TERMINAL_ERRORS.has(error))) {
          return null
        }
      }
    }
    throw Object.assign(new Error(`刷新登录状态失败（HTTP ${response.status}）`), { status: response.status })
  })().finally(() => {
    if (inFlight?.promise === promise) inFlight = null
  })

  inFlight = { sessionKey, token, promise }
  return promise
}
