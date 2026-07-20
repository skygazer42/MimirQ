import { describe, expect, it } from 'vitest'

import { sanitizeForwardedHeaders } from './trusted-forwarding.mjs'

describe('sanitizeForwardedHeaders', () => {
  it.each([
    ['forged single value', '198.51.100.8'],
    ['forged proxy chain', '198.51.100.8, 10.0.0.4'],
    ['missing header', undefined],
  ])('replaces %s with the TCP peer', (_case, supplied) => {
    const headers: Record<string, string | string[] | undefined> = {
      'x-forwarded-for': supplied,
      'x-forwarded-host': 'evil.example',
      'x-forwarded-port': '443',
      'x-forwarded-proto': 'https',
      'x-real-ip': '127.0.0.1',
    }

    sanitizeForwardedHeaders(headers, '::ffff:203.0.113.20')

    expect(headers['x-forwarded-for']).toBe('203.0.113.20')
    expect(headers['x-forwarded-host']).toBeUndefined()
    expect(headers['x-forwarded-port']).toBeUndefined()
    expect(headers['x-forwarded-proto']).toBeUndefined()
    expect(headers['x-real-ip']).toBeUndefined()
  })

  it('removes forwarding identity when no TCP peer is available', () => {
    const headers = { 'x-forwarded-for': '127.0.0.1', 'x-real-ip': '127.0.0.1' }

    sanitizeForwardedHeaders(headers, undefined)

    expect(headers).toEqual({})
  })
})
