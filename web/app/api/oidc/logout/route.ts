import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'

const REFRESH_COOKIE_NAME = 'mimirq_oidc_refresh_token'
const PROVIDER_COOKIE_NAME = 'mimirq_oidc_provider_id'

function jsonNoStore(data: any, init?: { status?: number }) {
  const resp = NextResponse.json(data, init)
  resp.headers.set('Cache-Control', 'no-store')
  resp.headers.set('Pragma', 'no-cache')
  return resp
}

function readEnv(name: string): string {
  return String(process.env[name] || '').trim()
}

function isFalsey(value: string): boolean {
  const v = String(value || '').trim().toLowerCase()
  return v === '0' || v === 'false' || v === 'no' || v === 'off' || v === 'disabled'
}

function requireSameOrigin(req: NextRequest): boolean {
  const origin = String(req.headers.get('origin') || '').trim()
  if (!origin) return false

  const xfProto = String(req.headers.get('x-forwarded-proto') || '').trim()
  const xfHost = String(req.headers.get('x-forwarded-host') || '').trim()
  const expected = xfProto && xfHost ? `${xfProto}://${xfHost}` : req.nextUrl.origin
  return origin === expected
}

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
    name: REFRESH_COOKIE_NAME,
    value: '',
    httpOnly: true,
    secure,
    sameSite: 'lax',
    path: '/api/oidc',
    maxAge: 0,
  })
  resp.cookies.set({
    name: PROVIDER_COOKIE_NAME,
    value: '',
    httpOnly: true,
    secure,
    sameSite: 'lax',
    path: '/api/oidc',
    maxAge: 0,
  })
  return resp
}
