import type { NextRequest } from 'next/server'

import { API_V1_BASE_URL } from '@/lib/env'
import { SAML_BRIDGE_COOKIE_NAME } from '@/lib/saml-session'
import { clearSamlBridgeCookie, jsonNoStore, requireSameOrigin } from '@/lib/server-auth-route'

export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  if (!requireSameOrigin(req)) {
    return jsonNoStore({ error: 'saml_invalid_origin' }, { status: 403 })
  }

  const code = req.cookies.get(SAML_BRIDGE_COOKIE_NAME)?.value.trim()
  if (code === undefined || code === '') {
    return clearSamlBridgeCookie(jsonNoStore({ error: 'Missing SAML sign-in session.' }, { status: 400 }))
  }

  const backendRes = await fetch(`${API_V1_BASE_URL}/auth/saml/bridge/consume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ code }),
  }).catch(() => null)

  if (!backendRes) {
    return clearSamlBridgeCookie(jsonNoStore({ error: 'Unable to reach auth backend' }, { status: 502 }))
  }

  const payload: unknown = await backendRes.json().catch(() => null)
  if (payload === null) {
    const error = backendRes.ok ? 'saml_invalid_session' : 'Invalid SAML bridge response'
    const status = backendRes.ok ? 502 : backendRes.status
    return clearSamlBridgeCookie(jsonNoStore({ error }, { status }))
  }
  return clearSamlBridgeCookie(jsonNoStore(payload, { status: backendRes.status }))
}
