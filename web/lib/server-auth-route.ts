import 'server-only'

import { type NextRequest, NextResponse } from 'next/server'

import { SAML_BRIDGE_COOKIE_NAME, SAML_BRIDGE_COOKIE_PATH } from '@/lib/saml-session'

export const OIDC_REFRESH_COOKIE_NAME = 'mimirq_oidc_refresh_token'
export const OIDC_PROVIDER_COOKIE_NAME = 'mimirq_oidc_provider_id'

export function jsonNoStore(data: unknown, init?: ResponseInit): NextResponse<unknown> {
  const response = NextResponse.json(data, init)
  response.headers.set('Cache-Control', 'no-store')
  response.headers.set('Pragma', 'no-cache')
  return response
}

export function readEnv(name: string): string {
  return process.env[name]?.trim() ?? ''
}

export function isFalsey(value: string): boolean {
  const normalizedValue = value.trim().toLowerCase()
  return (
    normalizedValue === '0' ||
    normalizedValue === 'false' ||
    normalizedValue === 'no' ||
    normalizedValue === 'off' ||
    normalizedValue === 'disabled'
  )
}

function normalizeOrigin(value: string | null): string | null {
  const trimmedValue = value?.trim()
  if (!trimmedValue) {
    return null
  }

  try {
    return new URL(trimmedValue).origin
  } catch {
    return null
  }
}

export function requireSameOrigin(req: NextRequest): boolean {
  const origin = normalizeOrigin(req.headers.get('origin'))
  if (!origin) {
    return false
  }

  const forwardedProto = req.headers.get('x-forwarded-proto')?.trim()
  const forwardedHost = req.headers.get('x-forwarded-host')?.trim()
  const expectedOrigin = normalizeOrigin(
    forwardedProto && forwardedHost ? `${forwardedProto}://${forwardedHost}` : req.nextUrl.origin,
  )

  return expectedOrigin === origin
}

export async function discoverOidcTokenEndpoint(issuer: string): Promise<string> {
  const response = await fetch(`${issuer}/.well-known/openid-configuration`, { method: 'GET' })
  if (!response.ok) throw new Error(`oidc_discovery_failed_${response.status}`)

  const metadata: unknown = await response.json().catch(() => null)
  if (typeof metadata !== 'object' || metadata === null || !('token_endpoint' in metadata)) {
    throw new Error('oidc_discovery_missing_endpoints')
  }
  const tokenEndpoint = typeof metadata.token_endpoint === 'string' ? metadata.token_endpoint.trim() : undefined
  if (tokenEndpoint === undefined || tokenEndpoint === '') throw new Error('oidc_discovery_missing_endpoints')
  return tokenEndpoint
}

export function oidcClientBasicAuthorization(clientId: string, clientSecret: string): string {
  const encode = (value: string) => new URLSearchParams([['', value]]).toString().slice(1)
  const credentials = `${encode(clientId)}:${encode(clientSecret)}`
  return `Basic ${Buffer.from(credentials).toString('base64')}`
}

export function normalizeOidcTokenType(value: unknown): string {
  const tokenType = typeof value === 'string' ? value.trim().toLowerCase() : undefined
  return tokenType === undefined || tokenType === '' ? 'bearer' : tokenType
}

export function isSamlEnabled(): boolean {
  const enabled = readEnv('SAML_ENABLED')
  return enabled !== '' && !isFalsey(enabled)
}

export function clearSamlBridgeCookie(response: NextResponse): NextResponse {
  response.cookies.set({
    name: SAML_BRIDGE_COOKIE_NAME,
    value: '',
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: SAML_BRIDGE_COOKIE_PATH,
    maxAge: 0,
  })
  return response
}
