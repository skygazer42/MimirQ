import { NextRequest, NextResponse } from 'next/server'

import { buildCspHeaderValue, createCspNonce } from './lib/security/csp'

const isDevelopment = process.env.NODE_ENV !== 'production'

function shouldUpgradeInsecureRequests(request: NextRequest): boolean {
  if (isDevelopment) return false

  const forwardedProto = request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim().toLowerCase()
  const protocol = forwardedProto || request.nextUrl.protocol.replace(/:$/, '').toLowerCase()

  return protocol === 'https'
}

export function proxy(request: NextRequest) {
  const nonce = createCspNonce()
  const cspHeader = buildCspHeaderValue({
    isDevelopment,
    nonce,
    upgradeInsecureRequests: shouldUpgradeInsecureRequests(request),
  })

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-nonce', nonce)
  requestHeaders.set('Content-Security-Policy', cspHeader)

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  })
  response.headers.set('Content-Security-Policy', cspHeader)

  return response
}

export const config = {
  matcher: [
    {
      source: '/((?!api|_next|.*\\..*).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
}
