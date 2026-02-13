import { NextRequest, NextResponse } from 'next/server'

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

const REFRESH_COOKIE_NAME = 'mimirq_oidc_refresh_token'

function readEnv(name: string): string {
  return String(process.env[name] || '').trim()
}

function isFalsey(value: string): boolean {
  const v = String(value || '').trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off' || v === 'disabled'
}

function resolveIssuer(): string {
  return (readEnv('OIDC_ISSUER') || readEnv('NEXT_PUBLIC_OIDC_ISSUER')).replace(/\/+$/, '')
}

function resolveClientId(): string {
  return readEnv('OIDC_CLIENT_ID') || readEnv('NEXT_PUBLIC_OIDC_CLIENT_ID')
}

function resolveClientSecret(): string {
  return readEnv('OIDC_CLIENT_SECRET')
}

function resolveClientAuthMethod(): 'basic' | 'post' {
  const raw = (readEnv('OIDC_CLIENT_AUTH_METHOD') || '').trim().toLowerCase()
  return raw === 'post' ? 'post' : 'basic'
}

function requireSameOrigin(req: NextRequest): boolean {
  const origin = String(req.headers.get('origin') || '').trim()
  if (!origin) return false

  const xfProto = String(req.headers.get('x-forwarded-proto') || '').trim()
  const xfHost = String(req.headers.get('x-forwarded-host') || '').trim()
  const expected = xfProto && xfHost ? `${xfProto}://${xfHost}` : req.nextUrl.origin
  return origin === expected
}

async function discoverTokenEndpoint(issuer: string): Promise<OidcDiscovery> {
  const url = `${issuer}/.well-known/openid-configuration`
  const res = await fetch(url, { method: 'GET' })
  if (!res.ok) {
    throw new Error(`oidc_discovery_failed_${res.status}`)
  }
  const data = (await res.json().catch(() => null)) as any
  const tokenEndpoint = String(data?.token_endpoint || '').trim()
  if (!tokenEndpoint) {
    throw new Error('oidc_discovery_missing_endpoints')
  }
  return { token_endpoint: tokenEndpoint }
}

function normalizeTokenType(raw: unknown): string {
  const t = String(raw || '').trim()
  return t ? t.toLowerCase() : 'bearer'
}

export async function POST(req: NextRequest) {
  const enabled = readEnv('OIDC_SERVER_EXCHANGE_ENABLED')
  if (enabled && isFalsey(enabled)) {
    return NextResponse.json({ error: 'oidc_server_exchange_disabled' }, { status: 400 })
  }
  if (!requireSameOrigin(req)) {
    return NextResponse.json({ error: 'oidc_invalid_origin' }, { status: 403 })
  }

  const issuer = resolveIssuer()
  const clientId = resolveClientId()
  if (!issuer || !clientId) {
    return NextResponse.json({ error: 'oidc_not_configured' }, { status: 400 })
  }

  const refreshToken = String(req.cookies.get(REFRESH_COOKIE_NAME)?.value || '').trim()
  if (!refreshToken) {
    return NextResponse.json({ error: 'oidc_missing_refresh_token' }, { status: 401 })
  }

  let tokenEndpoint = ''
  try {
    tokenEndpoint = (await discoverTokenEndpoint(issuer)).token_endpoint
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || 'oidc_discovery_failed') }, { status: 400 })
  }

  const secret = resolveClientSecret()
  const authMethod = resolveClientAuthMethod()

  const form = new URLSearchParams()
  form.set('grant_type', 'refresh_token')
  form.set('client_id', clientId)
  form.set('refresh_token', refreshToken)
  if (secret && authMethod === 'post') {
    form.set('client_secret', secret)
  }

  const headers: Record<string, string> = { 'Content-Type': 'application/x-www-form-urlencoded' }
  if (secret && authMethod === 'basic') {
    headers.Authorization = `Basic ${Buffer.from(`${clientId}:${secret}`).toString('base64')}`
  }

  const res = await fetch(tokenEndpoint, {
    method: 'POST',
    headers,
    body: form.toString(),
  })

  const data = (await res.json().catch(() => null)) as TokenResponse | null
  if (!res.ok) {
    const msg = String(data?.error_description || data?.error || '').trim()
    const secure = process.env.NODE_ENV === 'production'
    const resp = NextResponse.json({ error: msg || `oidc_token_refresh_failed_${res.status}` }, { status: 400 })
    // Best-effort: clear refresh token on invalid_grant-like responses.
    resp.cookies.set({
      name: REFRESH_COOKIE_NAME,
      value: '',
      httpOnly: true,
      secure,
      sameSite: 'lax',
      path: '/api/oidc',
      maxAge: 0,
    })
    return resp
  }

  const accessToken = String(data?.access_token || '').trim()
  if (!accessToken) {
    return NextResponse.json({ error: 'oidc_missing_access_token' }, { status: 400 })
  }

  const out = {
    access_token: accessToken,
    token_type: normalizeTokenType(data?.token_type),
    expires_in: Number.isFinite(Number(data?.expires_in)) ? Number(data?.expires_in) : 3600,
    id_token: data?.id_token ? String(data.id_token) : undefined,
  }

  const resp = NextResponse.json(out)
  const secure = process.env.NODE_ENV === 'production'
  const nextRefresh = String(data?.refresh_token || '').trim()
  if (nextRefresh) {
    resp.cookies.set({
      name: REFRESH_COOKIE_NAME,
      value: nextRefresh,
      httpOnly: true,
      secure,
      sameSite: 'lax',
      path: '/api/oidc',
      maxAge: 30 * 24 * 60 * 60,
    })
  }
  return resp
}
