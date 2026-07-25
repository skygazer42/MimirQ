import 'server-only'

import { type NextRequest, NextResponse } from 'next/server'

export const OIDC_REFRESH_COOKIE_NAME = 'mimirq_oidc_refresh_token'
export const OIDC_PROVIDER_COOKIE_NAME = 'mimirq_oidc_provider_id'

export function jsonNoStore(data: unknown, init?: ResponseInit): NextResponse<unknown> {
  const response = NextResponse.json(data, init)
  response.headers.set('Cache-Control', 'no-store')
  response.headers.set('Pragma', 'no-cache')
  return response
}

export function readEnv(name: string): string {
  return String(process.env[name] || '').trim()
}

export function isFalsey(value: string): boolean {
  const normalizedValue = String(value || '').trim().toLowerCase()
  return (
    normalizedValue === '0'
    || normalizedValue === 'false'
    || normalizedValue === 'no'
    || normalizedValue === 'off'
    || normalizedValue === 'disabled'
  )
}

function normalizeOrigin(value: string): string | null {
  const trimmedValue = String(value || '').trim()
  if (!trimmedValue) {
    return null
  }

  try {
    return new URL(trimmedValue).origin
  }
  catch {
    return null
  }
}

export function requireSameOrigin(req: NextRequest): boolean {
  const origin = normalizeOrigin(req.headers.get('origin') || '')
  if (!origin) {
    return false
  }

  const forwardedProto = String(req.headers.get('x-forwarded-proto') || '').trim()
  const forwardedHost = String(req.headers.get('x-forwarded-host') || '').trim()
  const expectedOrigin = normalizeOrigin(
    forwardedProto && forwardedHost
      ? `${forwardedProto}://${forwardedHost}`
      : req.nextUrl.origin,
  )

  return expectedOrigin === origin
}
