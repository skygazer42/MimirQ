'use client'

import type { AuthToken } from '@/types'
import { getAccessToken, getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'

type RefreshResponse = {
  access_token?: string
  token_type?: string
  expires_in?: number
  id_token?: string
  error?: string
}

function normalizeTokenType(raw: unknown): string {
  const t = toTrimmedPrimitiveString(raw)
  return t ? t.toLowerCase() : 'bearer'
}

let inFlight: {
  sessionRevision: number
  scope: string
  token: string | null
  promise: Promise<AuthToken | null>
} | null = null

export function __resetOidcRefreshForTests() {
  inFlight = null
}

export async function tryRefreshOidcAccessToken(): Promise<AuthToken | null> {
  const sessionRevision = getAuthSessionRevision()
  const scope = getAuthCacheScope()
  const token = getAccessToken()
  if (inFlight?.sessionRevision === sessionRevision && inFlight.scope === scope && inFlight.token === token) {
    return inFlight.promise
  }

  const promise = (async () => {
    try {
      const res = await fetch('/api/oidc/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        cache: 'no-store',
      })
      const data = (await res.json().catch(() => null)) as RefreshResponse | null
      if (!res.ok) return null

      const accessToken = String(data?.access_token || '').trim()
      if (!accessToken) return null

      const expiresIn = Number(data?.expires_in)
      return {
        access_token: accessToken,
        token_type: normalizeTokenType(data?.token_type),
        expires_in: Number.isFinite(expiresIn) ? expiresIn : 3600,
      }
    } catch {
      return null
    }
  })().finally(() => {
    if (inFlight?.promise === promise) inFlight = null
  })

  inFlight = { sessionRevision, scope, token, promise }
  return promise
}
