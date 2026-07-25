// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
}))

vi.mock('@/lib/env', () => ({
  API_V1_BASE_URL: 'https://api.example.com/api/v1',
}))

import { GET } from './route'

function makeRequest(query = '') {
  return new NextRequest(`https://app.example.com/api/saml/metadata${query}`, {
    method: 'GET',
  })
}

describe('SAML metadata route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', mocks.fetch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.SAML_ENABLED
  })

  it('stays disabled by default and returns a no-store 404 without contacting the backend', async () => {
    const response = await GET(makeRequest())

    expect(response.status).toBe(404)
    expect(await response.text()).toBe('Not Found')
    expect(response.headers.get('cache-control')).toBe('no-store')
    expect(mocks.fetch).not.toHaveBeenCalled()
  })

  it('forwards provider_id and preserves the no-store XML contract when enabled', async () => {
    process.env.SAML_ENABLED = 'true'
    mocks.fetch.mockResolvedValue(new Response('<xml>ok</xml>', { status: 200 }))

    const response = await GET(makeRequest('?provider_id=default'))

    expect(response.status).toBe(200)
    expect(await response.text()).toBe('<xml>ok</xml>')
    expect(response.headers.get('content-type')).toBe('application/samlmetadata+xml; charset=utf-8')
    expect(response.headers.get('cache-control')).toBe('no-store')
    expect(mocks.fetch).toHaveBeenCalledWith(
      new URL('https://api.example.com/api/v1/auth/saml/metadata?provider_id=default'),
      { method: 'GET', cache: 'no-store' }
    )
  })

  it('returns a bounded 502 when the auth backend cannot be reached', async () => {
    process.env.SAML_ENABLED = 'true'
    mocks.fetch.mockRejectedValue(new Error('network down'))

    const response = await GET(makeRequest())

    expect(response.status).toBe(502)
    expect(await response.text()).toBe('Unable to reach auth backend')
    expect(response.headers.get('cache-control')).toBe('no-store')
  })
})
