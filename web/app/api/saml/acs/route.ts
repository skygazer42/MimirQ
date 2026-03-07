import { NextRequest, NextResponse } from 'next/server'

import { API_V1_BASE_URL } from '@/lib/env'
import {
  SAML_BRIDGE_COOKIE_NAME,
  SAML_BRIDGE_COOKIE_PATH,
  encodeSamlBridgeState,
  type SamlBridgeState,
} from '@/lib/saml-session'
import type { AuthResponse } from '@/types'

export const runtime = 'nodejs'

type SamlExchangeResult = AuthResponse & {
  return_to?: string
  detail?: string
  error?: string
}

function readEnv(name: string): string {
  return String(process.env[name] || '').trim()
}

function isFalsey(value: string): boolean {
  const v = String(value || '').trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off' || v === 'disabled'
}

function isSamlEnabled(): boolean {
  const enabled = readEnv('SAML_ENABLED')
  if (!enabled) return false
  return !isFalsey(enabled)
}

function resolveOrigin(req: Request): string {
  const xfProto = String(req.headers.get('x-forwarded-proto') || '').trim()
  const xfHost = String(req.headers.get('x-forwarded-host') || '').trim()
  if (xfProto && xfHost) return `${xfProto}://${xfHost}`
  return new URL(req.url).origin
}

function applyNoStore(resp: NextResponse) {
  resp.headers.set('Cache-Control', 'no-store')
  resp.headers.set('Pragma', 'no-cache')
  return resp
}

function jsonNoStore(data: any, init?: { status?: number }) {
  return applyNoStore(NextResponse.json(data, init))
}

function redirectWithBridgeState(req: Request, bridgeState: SamlBridgeState) {
  const resp = applyNoStore(NextResponse.redirect(new URL('/auth/saml/callback', req.url), 303))
  resp.cookies.set({
    name: SAML_BRIDGE_COOKIE_NAME,
    value: encodeSamlBridgeState(bridgeState),
    httpOnly: false,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: SAML_BRIDGE_COOKIE_PATH,
    maxAge: 60,
  })
  return resp
}

function buildErrorState(message: string): SamlBridgeState {
  const error = String(message || '').trim() || 'SAML sign-in failed'
  return { kind: 'error', error }
}

export async function POST(req: NextRequest) {
  if (!isSamlEnabled()) {
    return jsonNoStore({ error: 'saml_disabled' }, { status: 404 })
  }

  const form = await req.formData().catch(() => null)
  if (!form) {
    return redirectWithBridgeState(req, buildErrorState('Invalid SAML request'))
  }

  const samlResponse = String(form.get('SAMLResponse') || '').trim()
  if (!samlResponse) {
    return redirectWithBridgeState(req, buildErrorState('Missing SAMLResponse'))
  }

  const relayState = String(form.get('RelayState') || '').trim() || undefined
  const requestUrl = new URL(req.url)
  const providerId = String(form.get('provider_id') || requestUrl.searchParams.get('provider_id') || '').trim() || undefined

  const backendRes = await fetch(`${API_V1_BASE_URL}/auth/saml/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({
      provider_id: providerId,
      saml_response: samlResponse,
      relay_state: relayState,
      acs_url: `${resolveOrigin(req)}/api/saml/acs`,
    }),
  }).catch(() => null)

  if (!backendRes) {
    return redirectWithBridgeState(req, buildErrorState('Unable to reach auth backend'))
  }

  const payload = (await backendRes.json().catch(() => null)) as SamlExchangeResult | null
  if (!backendRes.ok) {
    return redirectWithBridgeState(
      req,
      buildErrorState(String(payload?.detail || payload?.error || `SAML sign-in failed (${backendRes.status})`)),
    )
  }

  if (!payload?.user || !payload?.token?.access_token) {
    return redirectWithBridgeState(req, buildErrorState('Auth backend returned an invalid SAML session'))
  }

  return redirectWithBridgeState(req, {
    kind: 'success',
    session: {
      user: payload.user,
      token: payload.token,
    },
    returnTo: String(payload.return_to || '/').trim() || '/',
  })
}
