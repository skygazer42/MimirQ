// @vitest-environment node

import { describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

vi.mock('server-only', () => ({}))

import { POST } from './route'

function makeRequest(origin = 'https://app.example.com') {
  return new NextRequest('https://app.example.com/api/oidc/logout', {
    method: 'POST',
    headers: { origin },
  })
}

describe('OIDC logout route', () => {
  it('rejects cross-origin logout requests', async () => {
    const response = await POST(makeRequest('https://evil.example.com'))

    expect(response.status).toBe(403)
    expect(await response.json()).toEqual({ error: 'oidc_invalid_origin' })
    expect(response.headers.get('cache-control')).toBe('no-store')
  })

  it('clears the OIDC cookies with a no-store response', async () => {
    const response = await POST(makeRequest())

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ ok: true })
    expect(response.headers.get('cache-control')).toBe('no-store')
    const cookie = response.headers.get('set-cookie')
    expect(cookie).toContain('mimirq_oidc_refresh_token=')
    expect(cookie).toContain('mimirq_oidc_provider_id=')
    expect(cookie).toContain('Max-Age=0')
    expect(cookie).toContain('Path=/api/oidc')
  })
})
