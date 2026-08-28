// @vitest-environment node

import { afterEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

vi.mock('server-only', () => ({}))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('long-running parsing proxy route', () => {
  it('forwards auth headers and query parameters to the internal backend', async () => {
    vi.stubEnv('API_INTERNAL_URL', 'http://mimirq-api:8000/')
    vi.stubEnv('NEXT_PUBLIC_API_LONG_TIMEOUT_MS', '654321')
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json(
        { document_id: 'doc-1', markdown_content: '# parsed' },
        { status: 200, headers: { 'X-Request-ID': 'request-1' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { POST } = await import('./route')
    const request = new NextRequest(
      'http://web:3000/api/v1/parsing/documents/doc-1/parse?parser_backend=deepdoc&image_ocr_enabled=true',
      {
        method: 'POST',
        headers: {
          authorization: 'Bearer test-token',
          'x-tenant-id': 'tenant-1',
          'x-user-id': 'user-1',
          'x-request-id': 'request-1',
        },
      },
    )

    const response = await POST(request, {
      params: Promise.resolve({ documentId: 'doc-1' }),
    })

    expect(fetchMock).toHaveBeenCalledWith(
      new URL(
        'http://mimirq-api:8000/api/v1/parsing/documents/doc-1/parse?parser_backend=deepdoc&image_ocr_enabled=true',
      ),
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        redirect: 'manual',
        headers: expect.any(Headers),
        signal: expect.any(AbortSignal),
      }),
    )
    const forwarded = fetchMock.mock.calls[0]?.[1]?.headers as Headers
    expect(forwarded.get('authorization')).toBe('Bearer test-token')
    expect(forwarded.get('x-tenant-id')).toBe('tenant-1')
    expect(forwarded.get('x-user-id')).toBe('user-1')
    expect(forwarded.get('host')).toBeNull()
    expect(response.status).toBe(200)
    expect(response.headers.get('x-request-id')).toBe('request-1')
    expect(await response.json()).toEqual({
      document_id: 'doc-1',
      markdown_content: '# parsed',
    })
  })

  it('preserves backend error responses instead of converting them to a proxy 500', async () => {
    vi.stubEnv('API_INTERNAL_URL', 'http://mimirq-api:8000')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        Response.json({ detail: 'DeepDoc rejected the file' }, { status: 422 }),
      ),
    )
    const { POST } = await import('./route')

    const response = await POST(
      new NextRequest('http://web:3000/api/v1/parsing/documents/doc-2/parse', {
        method: 'POST',
      }),
      { params: Promise.resolve({ documentId: 'doc-2' }) },
    )

    expect(response.status).toBe(422)
    await expect(response.json()).resolves.toEqual({ detail: 'DeepDoc rejected the file' })
  })

  it.each([
    ['TimeoutError', 504, 'Parsing request timed out before the backend responded'],
    ['TypeError', 502, 'Parsing backend is unavailable'],
  ])('maps %s failures to a stable gateway response', async (name, status, detail) => {
    vi.stubEnv('API_INTERNAL_URL', 'http://mimirq-api:8000')
    const error = new Error('proxy failed')
    error.name = name
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error))
    const { POST } = await import('./route')

    const response = await POST(
      new NextRequest('http://web:3000/api/v1/parsing/documents/doc-3/parse', {
        method: 'POST',
      }),
      { params: Promise.resolve({ documentId: 'doc-3' }) },
    )

    expect(response.status).toBe(status)
    expect(response.headers.get('cache-control')).toBe('no-store')
    await expect(response.json()).resolves.toEqual({ detail })
  })
})
