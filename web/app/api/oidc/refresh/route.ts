import { NextRequest } from 'next/server'

import { getOidcServerProvidersFromEnv, resolveOidcServerProvider } from '@/lib/oidc-providers'
import {
  OIDC_PROVIDER_COOKIE_NAME,
  OIDC_REFRESH_COOKIE_NAME,
  isFalsey,
  jsonNoStore,
  readEnv,
  requireSameOrigin,
} from '@/lib/server-auth-route'

export const runtime = 'nodejs'

type OidcDiscovery = {
  token_endpoint: string
}

type TokenResponse = {
  access_token?: string
  token_type?: string
  expires_in?: number
  refresh_token?: string
  id_token?: string
  error?: string
  error_description?: string
}

async function discoverTokenEndpoint(issuer: string): Promise<OidcDiscovery> {
  const url = `${issuer}/.well-known/openid-configuration`
  const res = await fetch(url, { method: 'GET' })
  if (!res.ok) {
    throw new Error(`oidc_discovery_failed_${res.status}`)
  }
  const data = (await res.json().catch(() => null))
  const tokenEndpoint = typeof data?.token_endpoint === 'string' ? data.token_endpoint.trim() : ''
  if (!tokenEndpoint) {
    throw new Error('oidc_discovery_missing_endpoints')
  }
  return { token_endpoint: tokenEndpoint }
}

function normalizeTokenType(raw: unknown): string {
  const t = typeof raw === 'string' ? raw.trim() : ''
  return t ? t.toLowerCase() : 'bearer'
}

function isTerminalRefreshFailure(errorCode: string): boolean {
  return errorCode === 'invalid_grant'
}

export async function POST(req: NextRequest) {
  const enabled = readEnv('OIDC_SERVER_EXCHANGE_ENABLED')
  if (enabled && isFalsey(enabled)) {
    return jsonNoStore({ error: 'oidc_server_exchange_disabled' }, { status: 400 })
  }
  if (!requireSameOrigin(req)) {
    return jsonNoStore({ error: 'oidc_invalid_origin' }, { status: 403 })
  }

  const providerId = String(req.cookies.get(OIDC_PROVIDER_COOKIE_NAME)?.value || '').trim() || undefined
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

  const refreshToken = req.cookies.get(OIDC_REFRESH_COOKIE_NAME)?.value?.trim() ?? ''
  if (!refreshToken) {
    return jsonNoStore({ error: 'oidc_missing_refresh_token' }, { status: 401 })
  }

  let tokenEndpoint = ''
  try {
    tokenEndpoint = (await discoverTokenEndpoint(issuer)).token_endpoint
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'oidc_discovery_failed'
    return jsonNoStore({ error: String(message || 'oidc_discovery_failed') }, { status: 400 })
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
    const credentials = `${clientId}:${secret}`
    headers.Authorization = `Basic ${Buffer.from(credentials).toString('base64')}`
  }

  const res = await fetch(tokenEndpoint, {
    method: 'POST',
    headers,
    body: form.toString(),
  })

  const data = (await res.json().catch(() => null)) as TokenResponse | null
  if (!res.ok) {
    const errorCode = String(data?.error || '').trim().toLowerCase()
    const msg = String(data?.error_description || data?.error || '').trim()
    const secure = process.env.NODE_ENV === 'production'
    const status = res.status === 429 || res.status >= 500 ? res.status : 400
    const resp = jsonNoStore({ error: msg || `oidc_token_refresh_failed_${res.status}` }, { status })
    if (isTerminalRefreshFailure(errorCode)) {
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

  const accessToken = String(data?.access_token || '').trim()
  if (!accessToken) {
    return jsonNoStore({ error: 'oidc_missing_access_token' }, { status: 400 })
  }

  const out = {
    access_token: accessToken,
    token_type: normalizeTokenType(data?.token_type),
    expires_in: Number.isFinite(Number(data?.expires_in)) ? Number(data?.expires_in) : 3600,
    id_token: data?.id_token ? String(data.id_token) : undefined,
  }

  const resp = jsonNoStore(out)
  const secure = process.env.NODE_ENV === 'production'
  const nextRefresh = String(data?.refresh_token || '').trim()
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
