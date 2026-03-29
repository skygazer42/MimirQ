import { afterEach, describe, expect, it, vi } from 'vitest'
import { observabilityApi } from './api/observability'

const originalFetch = globalThis.fetch
const originalUserId = process.env.NEXT_PUBLIC_USER_ID
const originalTenantId = process.env.NEXT_PUBLIC_TENANT_ID

describe('observabilityApi.reportFrontendVital', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch
    if (originalUserId === undefined) {
      delete process.env.NEXT_PUBLIC_USER_ID
    } else {
      process.env.NEXT_PUBLIC_USER_ID = originalUserId
    }
    if (originalTenantId === undefined) {
      delete process.env.NEXT_PUBLIC_TENANT_ID
    } else {
      process.env.NEXT_PUBLIC_TENANT_ID = originalTenantId
    }
  })

  it('uses a keepalive fetch with auth headers for vitals transport', async () => {
    process.env.NEXT_PUBLIC_USER_ID = 'demo-user'
    process.env.NEXT_PUBLIC_TENANT_ID = '00000000-0000-0000-0000-000000000001'
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }))
    globalThis.fetch = fetchMock as typeof fetch

    await observabilityApi.reportFrontendVital(
      {
        id: 'metric-1',
        name: 'LCP',
        value: 1234,
        page: '/chat',
      },
      { keepalive: true }
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/observability/frontend-vitals')
    expect(init.method).toBe('POST')
    expect(init.keepalive).toBe(true)
    expect(init.headers).toMatchObject({
      'Content-Type': 'application/json',
      'X-User-ID': 'demo-user',
      'X-Tenant-ID': '00000000-0000-0000-0000-000000000001',
    })
    expect(init.body).toBe(JSON.stringify({ id: 'metric-1', name: 'LCP', value: 1234, page: '/chat' }))
  })

  it('surfaces backend fetch errors when vital transport fails', async () => {
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: 'telemetry rejected', request_id: 'rid-body' }), {
          status: 500,
          headers: {
            'Content-Type': 'application/json',
            'X-Request-ID': 'rid-header',
          },
        })
    )
    globalThis.fetch = fetchMock as typeof fetch

    await expect(
      observabilityApi.reportFrontendVital({
        id: 'metric-2',
        name: 'CLS',
        value: 0.12,
        page: '/chat',
      })
    ).rejects.toThrow(/telemetry rejected/)

    await expect(
      observabilityApi.reportFrontendVital({
        id: 'metric-3',
        name: 'INP',
        value: 123,
        page: '/chat',
      })
    ).rejects.toThrow(/request_id=rid-body/)
  })
})

describe('observabilityApi.reportFrontendTrace', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch
    if (originalUserId === undefined) {
      delete process.env.NEXT_PUBLIC_USER_ID
    } else {
      process.env.NEXT_PUBLIC_USER_ID = originalUserId
    }
    if (originalTenantId === undefined) {
      delete process.env.NEXT_PUBLIC_TENANT_ID
    } else {
      process.env.NEXT_PUBLIC_TENANT_ID = originalTenantId
    }
  })

  it('uses keepalive fetch with auth headers for frontend trace transport', async () => {
    process.env.NEXT_PUBLIC_USER_ID = 'demo-user'
    process.env.NEXT_PUBLIC_TENANT_ID = '00000000-0000-0000-0000-000000000001'
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }))
    globalThis.fetch = fetchMock as typeof fetch

    await observabilityApi.reportFrontendTrace(
      {
        event: 'graph_render_projection',
        duration_ms: 16.5,
        component: 'graph-display-filters',
        page: '/graph',
        input_node_count: 48,
        output_node_count: 12,
      },
      { keepalive: true }
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/observability/frontend-traces')
    expect(init.method).toBe('POST')
    expect(init.keepalive).toBe(true)
    expect(init.headers).toMatchObject({
      'Content-Type': 'application/json',
      'X-User-ID': 'demo-user',
      'X-Tenant-ID': '00000000-0000-0000-0000-000000000001',
    })
    expect(init.body).toBe(
      JSON.stringify({
        event: 'graph_render_projection',
        duration_ms: 16.5,
        component: 'graph-display-filters',
        page: '/graph',
        input_node_count: 48,
        output_node_count: 12,
      })
    )
  })
})
