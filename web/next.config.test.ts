import { describe, expect, it } from 'vitest'

import nextConfig, {
  resolveAllowedDevOrigins,
  resolveBackendProxyBase,
} from './next.config.mjs'

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

  it('allows localhost plus LAN development origins for Next dev resources', () => {
    const origins = resolveAllowedDevOrigins(
      {
        NEXT_ALLOWED_DEV_ORIGINS: 'demo.internal, 192.168.50.20',
        NODE_ENV: 'development',
      },
      {
        eth0: [
          { address: '192.168.3.6', family: 'IPv4', internal: false, netmask: '255.255.255.0', mac: '00:11:22:33:44:55', cidr: '192.168.3.6/24' },
          { address: '8.8.8.8', family: 'IPv4', internal: false, netmask: '255.255.255.0', mac: '00:11:22:33:44:56', cidr: '8.8.8.8/24' },
        ],
        lo: [{ address: '127.0.0.1', family: 'IPv4', internal: true, netmask: '255.0.0.0', mac: '00:00:00:00:00:00', cidr: '127.0.0.1/8' }],
      }
    )

    expect(origins).toContain('localhost')
    expect(origins).toContain('127.0.0.1')
    expect(origins).toContain('0.0.0.0')
    expect(origins).toContain('192.168.3.6')
    expect(origins).toContain('192.168.50.20')
    expect(origins).toContain('demo.internal')
    expect(origins).not.toContain('8.8.8.8')
  })

  it('proxies /api/v1 to the backend using internal URL precedence', async () => {
    expect(
      resolveBackendProxyBase({
        API_INTERNAL_URL: 'http://mimirq-api:8000/',
        NEXT_PUBLIC_API_URL: 'http://localhost:8000',
        NODE_ENV: 'development',
      })
    ).toBe('http://mimirq-api:8000')

    expect(
      resolveBackendProxyBase({
        API_INTERNAL_URL: '',
        NEXT_PUBLIC_API_URL: 'http://localhost:8000/',
        NODE_ENV: 'development',
      })
    ).toBe('http://localhost:8000')

    expect(nextConfig.rewrites).toBeTypeOf('function')
    const rewrites = await nextConfig.rewrites!()
    expect(rewrites).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: '/api/v1/documents',
          destination: 'http://127.0.0.1:8000/api/v1/documents/',
        }),
        expect.objectContaining({
          source: '/api/v1/:path*',
        }),
      ])
    )
  })
})
