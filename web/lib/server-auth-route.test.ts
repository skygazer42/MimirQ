// @vitest-environment node

import { describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

vi.mock('server-only', () => ({}))

import { jsonNoStore, requireSameOrigin } from './server-auth-route'

describe('server auth route helpers', () => {
  it('treats default https ports as same-origin for proxied requests', () => {
    const request = new NextRequest('http://internal.example.local/api/oidc/refresh', {
      method: 'POST',
      headers: {
        origin: 'https://app.example.com:443',
        'x-forwarded-host': 'app.example.com',
        'x-forwarded-proto': 'https',
      },
    })

    expect(requireSameOrigin(request)).toBe(true)
  })

  it('treats default http ports as same-origin for direct requests', () => {
    const request = new NextRequest('http://app.example.com/api/oidc/refresh', {
      method: 'POST',
      headers: {
        origin: 'http://app.example.com:80',
      },
    })

    expect(requireSameOrigin(request)).toBe(true)
  })

  it('rejects non-default port mismatches', () => {
    const request = new NextRequest('http://internal.example.local/api/oidc/refresh', {
      method: 'POST',
      headers: {
        origin: 'https://app.example.com:8443',
        'x-forwarded-host': 'app.example.com',
        'x-forwarded-proto': 'https',
      },
    })

    expect(requireSameOrigin(request)).toBe(false)
  })

  it('rejects missing or malformed origins', () => {
    const missingOrigin = new NextRequest('https://app.example.com/api/oidc/refresh', {
      method: 'POST',
    })
    const malformedOrigin = new NextRequest('http://internal.example.local/api/oidc/refresh', {
      method: 'POST',
      headers: {
        origin: 'not a url',
        'x-forwarded-host': 'app.example.com',
        'x-forwarded-proto': 'https',
      },
    })
    const malformedForwardedOrigin = new NextRequest('http://internal.example.local/api/oidc/refresh', {
      method: 'POST',
      headers: {
        origin: 'https://app.example.com',
        'x-forwarded-host': 'bad host value',
        'x-forwarded-proto': 'https',
      },
    })

    expect(requireSameOrigin(missingOrigin)).toBe(false)
    expect(requireSameOrigin(malformedOrigin)).toBe(false)
    expect(requireSameOrigin(malformedForwardedOrigin)).toBe(false)
  })

  it('marks JSON responses as no-store', () => {
    const response = jsonNoStore({ ok: true }, { status: 202 })

    expect(response.status).toBe(202)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(response.headers.get('Pragma')).toBe('no-cache')
  })
})
