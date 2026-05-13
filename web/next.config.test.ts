import { describe, expect, it } from 'vitest'

import nextConfig from './next.config.mjs'

describe('next config security headers', () => {
  it('adds hardened response headers while leaving CSP to proxy nonce wiring', async () => {
    expect(nextConfig.headers).toBeTypeOf('function')

    const routes = await nextConfig.headers!()
    expect(routes).toHaveLength(1)
    expect(routes[0]?.source).toBe('/:path*')

    const headerMap = new Map(routes[0]?.headers?.map((header) => [header.key, header.value]))
    expect(headerMap.get('Referrer-Policy')).toBe('strict-origin-when-cross-origin')
    expect(headerMap.get('X-Content-Type-Options')).toBe('nosniff')
    expect(headerMap.get('X-Frame-Options')).toBe('SAMEORIGIN')
    expect(headerMap.get('Permissions-Policy')).toBe('camera=(), microphone=(), geolocation=()')
    expect(headerMap.has('Content-Security-Policy')).toBe(false)
  })
})
