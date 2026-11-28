import type { NextRequest } from 'next/server'

import { readOidcExpiresIn } from '@/lib/auth-response-schema'
import { getOidcServerProvidersFromEnv, resolveOidcServerProvider } from '@/lib/oidc-providers'
import { readNonEmptyString } from '@/lib/primitive-text'
import {
  OIDC_PROVIDER_COOKIE_NAME,
  OIDC_REFRESH_COOKIE_NAME,
  discoverOidcTokenEndpoint,
  isFalsey,
  jsonNoStore,
  normalizeOidcTokenType,
  oidcClientBasicAuthorization,
  readEnv,
  requireSameOrigin,
} from '@/lib/server-auth-route'

export const runtime = 'nodejs'

type TokenResponse = {
  access_token?: string
  token_type?: string
  expires_in?: unknown
  refresh_token?: string
  id_token?: string
  error?: string
  error_description?: string
}

export async function POST(req: NextRequest) {
  const enabled = readEnv('OIDC_SERVER_EXCHANGE_ENABLED')
  if (enabled && isFalsey(enabled)) {
    return jsonNoStore({ error: 'oidc_server_exchange_disabled' }, { status: 400 })
  }
  if (!requireSameOrigin(req)) {
    return jsonNoStore({ error: 'oidc_invalid_origin' }, { status: 403 })
  }

  const providerId = req.cookies.get(OIDC_PROVIDER_COOKIE_NAME)?.value.trim()
  const provider = resolveOidcServerProvider(providerId)
  if (!provider) {
    const available = getOidcServerProvidersFromEnv()
    if (available.length > 1) {
      return jsonNoStore({ error: 'oidc_provider_required' }, { status: 400 })
    }
    return jsonNoStore({ error: 'oidc_not_configured' }, { status: 400 })
  }
  const issuer = provider.issuer.trim()
  const clientId = provider.client_id.trim()

  const refreshToken = req.cookies.get(OIDC_REFRESH_COOKIE_NAME)?.value.trim()
  if (!refreshToken) {
    return jsonNoStore({ error: 'oidc_missing_refresh_token' }, { status: 401 })
  }

  let tokenEndpoint: string
  try {
    tokenEndpoint = await discoverOidcTokenEndpoint(issuer)
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'oidc_discovery_failed'
    return jsonNoStore({ error: message || 'oidc_discovery_failed' }, { status: 400 })
  }

  const secret = provider.client_secret?.trim() ?? ''
  const authMethod: 'basic' | 'post' = provider.client_auth_method === 'post' ? 'post' : 'basic'

  const form = new URLSearchParams()
  form.set('grant_type', 'refresh_token')
  form.set('client_id', clientId)
  form.set('refresh_token', refreshToken)
  if (secret && authMethod === 'post') {
    form.set('client_secret', secret)
  }

  const headers: Record<string, string> = { 'Content-Type': 'application/x-www-form-urlencoded' }
  if (secret && authMethod === 'basic') {
    headers.Authorization = oidcClientBasicAuthorization(clientId, secret)
  }

  const res = await fetch(tokenEndpoint, {
    method: 'POST',
    headers,
    body: form.toString(),
  }).catch(() => null)
  if (res === null) return jsonNoStore({ error: 'oidc_token_endpoint_unavailable' }, { status: 502 })

  const data = (await res.json().catch(() => null)) as TokenResponse | null
  if (!res.ok) {
    const error = readNonEmptyString(data?.error)
    const errorCode = error?.toLowerCase()
    const message = readNonEmptyString(data?.error_description) ?? error
    const secure = process.env.NODE_ENV === 'production'
    const status = res.status === 429 || res.status >= 500 ? res.status : 400
    const resp = jsonNoStore(
      { error: message ?? `oidc_token_refresh_failed_${res.status}`, code: errorCode },
      { status },
    )
    if (errorCode === 'invalid_grant') {
      // Terminal OAuth failures mean the stored refresh token is no longer usable.
      resp.cookies.set({
        name: OIDC_REFRESH_COOKIE_NAME,
        value: '',
        httpOnly: true,
        secure,
        sameSite: 'lax',
        path: '/api/oidc',
        maxAge: 0,
      })
      resp.cookies.set({
        name: OIDC_PROVIDER_COOKIE_NAME,
        value: '',
        httpOnly: true,
        secure,
        sameSite: 'lax',
        path: '/api/oidc',
        maxAge: 0,
      })
    }
    return resp
  }

  const accessToken = readNonEmptyString(data?.access_token)
  if (!accessToken) {
    return jsonNoStore({ error: 'oidc_missing_access_token' }, { status: 400 })
  }

  const expiresIn = readOidcExpiresIn(data?.expires_in)
  if (expiresIn === null) return jsonNoStore({ error: 'oidc_invalid_expiry' }, { status: 502 })

  const out = {
    access_token: accessToken,
    token_type: normalizeOidcTokenType(data?.token_type),
    expires_in: expiresIn,
    id_token: readNonEmptyString(data?.id_token),
  }

  const resp = jsonNoStore(out)
  const secure = process.env.NODE_ENV === 'production'
  const nextRefresh = readNonEmptyString(data?.refresh_token)
  if (nextRefresh) {
    resp.cookies.set({
      name: OIDC_REFRESH_COOKIE_NAME,
      value: nextRefresh,
      httpOnly: true,
      secure,
      sameSite: 'lax',
      path: '/api/oidc',
      maxAge: 30 * 24 * 60 * 60,
    })
    resp.cookies.set({
      name: OIDC_PROVIDER_COOKIE_NAME,
      value: provider.id,
      httpOnly: true,
      secure,
      sameSite: 'lax',
      path: '/api/oidc',
      maxAge: 30 * 24 * 60 * 60,
    })
  }
  return resp
}
