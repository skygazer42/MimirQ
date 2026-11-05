import { type NextRequest, NextResponse } from 'next/server'

import { API_V1_BASE_URL } from '@/lib/env'
import { SAML_CALLBACK_ERROR_FALLBACK, SAML_BRIDGE_COOKIE_NAME, SAML_BRIDGE_COOKIE_PATH } from '@/lib/saml-session'
import type { SAML_CALLBACK_ERROR_MESSAGES } from '@/lib/saml-session'
import { isFalsey, jsonNoStore, readEnv } from '@/lib/server-auth-route'
import type { OpenApiSchema } from '@/types/backend'

export const runtime = 'nodejs'

type SamlExchangeResult = Partial<Pick<OpenApiSchema<'SamlExchangeResponse'>, 'bridge_code' | 'user' | 'token'>>
type SamlCallbackErrorCode = keyof typeof SAML_CALLBACK_ERROR_MESSAGES

function isSamlEnabled(): boolean {
  const enabled = readEnv('SAML_ENABLED')
  if (!enabled) return false
  return !isFalsey(enabled)
}

function applyNoStore(resp: NextResponse) {
  resp.headers.set('Cache-Control', 'no-store')
  resp.headers.set('Pragma', 'no-cache')
  return resp
}

function clearBridgeCookie(resp: NextResponse) {
  resp.cookies.set({
    name: SAML_BRIDGE_COOKIE_NAME,
    value: '',
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: SAML_BRIDGE_COOKIE_PATH,
    maxAge: 0,
  })
  return resp
}

function redirectToCallback(req: Request, error?: SamlCallbackErrorCode) {
  const url = new URL('/auth/saml/callback', req.url)
  const errorCode = String(error || '').trim()
  if (errorCode) {
    url.searchParams.set('error', errorCode)
  }
  const resp = applyNoStore(NextResponse.redirect(url, 303))
  return errorCode ? clearBridgeCookie(resp) : resp
}

function mapExchangeError(status: number): SamlCallbackErrorCode {
  if (status === 400) return 'saml_invalid_request'
  if (status === 401) return 'saml_invalid_response'
  if (status === 403) return 'saml_access_denied'
  return SAML_CALLBACK_ERROR_FALLBACK
}

function getFormString(form: FormData, key: string): string {
  const value = form.get(key)
  return typeof value === 'string' ? value.trim() : ''
}

export async function POST(req: NextRequest) {
  if (!isSamlEnabled()) {
    return jsonNoStore({ error: 'saml_disabled' }, { status: 404 })
  }

  const form = await req.formData().catch(() => null)
  if (!form) {
    return redirectToCallback(req, 'saml_invalid_request')
  }

  const samlResponse = getFormString(form, 'SAMLResponse')
  if (!samlResponse) {
    return redirectToCallback(req, 'saml_missing_response')
  }

  const relayState = getFormString(form, 'RelayState') || undefined
  const requestUrl = new URL(req.url)
  const providerId =
    getFormString(form, 'provider_id') || requestUrl.searchParams.get('provider_id')?.trim() || undefined

  const backendRes = await fetch(`${API_V1_BASE_URL}/auth/saml/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({
      provider_id: providerId,
      saml_response: samlResponse,
      relay_state: relayState,
      bridge_mode: true,
    }),
  }).catch(() => null)

  if (!backendRes) {
    return redirectToCallback(req, 'saml_backend_unreachable')
  }

  const payload = (await backendRes.json().catch(() => null)) as SamlExchangeResult | null
  if (!backendRes.ok) {
    return redirectToCallback(req, mapExchangeError(backendRes.status))
  }

  const bridgeCode = String(payload?.bridge_code || '').trim()
  if (!payload?.user || !payload?.token?.access_token || !bridgeCode) {
    return redirectToCallback(req, 'saml_invalid_session')
  }

  const resp = redirectToCallback(req)
  resp.cookies.set({
    name: SAML_BRIDGE_COOKIE_NAME,
    value: bridgeCode,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: SAML_BRIDGE_COOKIE_PATH,
    maxAge: 60,
  })
  return resp
}
