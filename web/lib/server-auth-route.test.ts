// @vitest-environment node

import { describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

vi.mock('server-only', () => ({}))

import { jsonNoStore, requireSameOrigin } from './server-auth-route'

describe('server auth route helpers', () => {
  it('matches forwarded origins for proxied requests', () => {
    const request = new NextRequest('http://internal.example.local/api/oidc/refresh', {
      method: 'POST',
      headers: {
        origin: 'https://app.example.com',
        'x-forwarded-host': 'app.example.com',
        'x-forwarded-proto': 'https',
      },
    })

    expect(requireSameOrigin(request)).toBe(true)
  })

  it('marks JSON responses as no-store', () => {
    const response = jsonNoStore({ ok: true }, { status: 202 })

    expect(response.status).toBe(202)
    expect(response.headers.get('Cache-Control')).toBe('no-store')
    expect(response.headers.get('Pragma')).toBe('no-cache')
  })
})
