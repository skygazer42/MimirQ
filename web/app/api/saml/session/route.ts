import { NextRequest, NextResponse } from 'next/server'

import { API_V1_BASE_URL } from '@/lib/env'
import { SAML_BRIDGE_COOKIE_NAME, SAML_BRIDGE_COOKIE_PATH } from '@/lib/saml-session'
import { jsonNoStore, requireSameOrigin } from '@/lib/server-auth-route'

export const runtime = 'nodejs'

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

export async function POST(req: NextRequest) {
  if (!requireSameOrigin(req)) {
    return jsonNoStore({ error: 'saml_invalid_origin' }, { status: 403 })
  }

  const code = String(req.cookies.get(SAML_BRIDGE_COOKIE_NAME)?.value || '').trim()
  if (!code) {
    return clearBridgeCookie(jsonNoStore({ error: 'Missing SAML sign-in session.' }, { status: 400 }))
  }

  const backendRes = await fetch(`${API_V1_BASE_URL}/auth/saml/bridge/consume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ code }),
  }).catch(() => null)

  if (!backendRes) {
    return clearBridgeCookie(jsonNoStore({ error: 'Unable to reach auth backend' }, { status: 502 }))
  }

  const payload = await backendRes.json().catch(() => null)
  return clearBridgeCookie(jsonNoStore(payload ?? { error: 'Invalid SAML bridge response' }, { status: backendRes.status }))
}
