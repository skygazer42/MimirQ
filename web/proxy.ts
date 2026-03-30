import { NextRequest } from 'next/server'
import createMiddleware from 'next-intl/middleware'

import { routing } from './i18n/routing'
import { buildCspHeaderValue, createCspNonce } from './lib/security/csp'

const isDevelopment = process.env.NODE_ENV !== 'production'
const handleI18nRouting = createMiddleware(routing)

export function proxy(request: NextRequest) {
  const nonce = createCspNonce()
  const cspHeader = buildCspHeaderValue({
    isDevelopment,
    nonce,
  })

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-nonce', nonce)
  requestHeaders.set('Content-Security-Policy', cspHeader)

  const requestWithHeaders = new NextRequest(request, {
    headers: requestHeaders,
  })
  const response = handleI18nRouting(requestWithHeaders)
  response.headers.set('Content-Security-Policy', cspHeader)

  return response
}

export const config = {
  matcher: [
    {
      source: '/((?!api|_next/static|_next/image|favicon.ico).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
}
