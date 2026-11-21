import { type NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'

import { API_V1_BASE_URL } from '@/lib/env'
import { readNonEmptyString } from '@/lib/primitive-text'
import { recordSchema } from '@/lib/response-schema'
import {
  SAML_CALLBACK_ERROR_FALLBACK,
  SAML_BRIDGE_COOKIE_NAME,
  SAML_BRIDGE_COOKIE_PATH,
  type SAML_CALLBACK_ERROR_MESSAGES,
} from '@/lib/saml-session'
import { clearSamlBridgeCookie, isSamlEnabled, jsonNoStore } from '@/lib/server-auth-route'

export const runtime = 'nodejs'

type SamlCallbackErrorCode = keyof typeof SAML_CALLBACK_ERROR_MESSAGES

const samlBridgeExchangeSchema = z.object({
  bridge_code: z.string().trim().min(1),
  user: recordSchema,
  token: z.object({ access_token: z.string().trim().min(1) }),
})

function applyNoStore(resp: NextResponse) {
  resp.headers.set('Cache-Control', 'no-store')
  resp.headers.set('Pragma', 'no-cache')
  return resp
}

function redirectToCallback(req: Request, error?: SamlCallbackErrorCode) {
  const url = new URL('/auth/saml/callback', req.url)
  if (error !== undefined) {
    url.searchParams.set('error', error)
  }
  const resp = applyNoStore(NextResponse.redirect(url, 303))
  return error === undefined ? resp : clearSamlBridgeCookie(resp)
}

function mapExchangeError(status: number): SamlCallbackErrorCode {
  if (status === 400) return 'saml_invalid_request'
  if (status === 401) return 'saml_invalid_response'
  if (status === 403) return 'saml_access_denied'
  return SAML_CALLBACK_ERROR_FALLBACK
}

export async function POST(req: NextRequest) {
  if (!isSamlEnabled()) {
    return jsonNoStore({ error: 'saml_disabled' }, { status: 404 })
  }

  const form = await req.formData().catch(() => null)
  if (!form) {
    return redirectToCallback(req, 'saml_invalid_request')
  }

  const samlResponse = readNonEmptyString(form.get('SAMLResponse'))
  if (samlResponse === undefined) {
    return redirectToCallback(req, 'saml_missing_response')
  }

  const relayState = readNonEmptyString(form.get('RelayState'))
  const providerId =
    readNonEmptyString(form.get('provider_id')) ?? readNonEmptyString(req.nextUrl.searchParams.get('provider_id'))

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

  if (!backendRes.ok) {
    return redirectToCallback(req, mapExchangeError(backendRes.status))
  }

  const exchange = samlBridgeExchangeSchema.safeParse(await backendRes.json().catch(() => null))
  if (!exchange.success) {
    return redirectToCallback(req, 'saml_invalid_session')
  }

  const resp = redirectToCallback(req)
  resp.cookies.set({
    name: SAML_BRIDGE_COOKIE_NAME,
    value: exchange.data.bridge_code,
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: SAML_BRIDGE_COOKIE_PATH,
    maxAge: 60,
  })
  return resp
}
