import { NextRequest } from 'next/server'

import {
  OIDC_PROVIDER_COOKIE_NAME,
  OIDC_REFRESH_COOKIE_NAME,
  isFalsey,
  jsonNoStore,
  readEnv,
  requireSameOrigin,
} from '@/lib/server-auth-route'

export const runtime = 'nodejs'

export async function POST(req: NextRequest) {
  const enabled = readEnv('OIDC_SERVER_EXCHANGE_ENABLED')
  if (enabled && isFalsey(enabled)) {
    return jsonNoStore({ ok: true })
  }
  if (!requireSameOrigin(req)) {
    return jsonNoStore({ error: 'oidc_invalid_origin' }, { status: 403 })
  }

  const resp = jsonNoStore({ ok: true })
  const secure = process.env.NODE_ENV === 'production'
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
  return resp
}
