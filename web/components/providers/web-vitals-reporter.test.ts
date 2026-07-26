// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  callback: undefined as ((metric: Record<string, unknown>) => void) | undefined,
  report: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('next/web-vitals', () => ({
  useReportWebVitals: (callback: (metric: Record<string, unknown>) => void) => {
    mocks.callback = callback
  },
}))
vi.mock('@/i18n/navigation', () => ({ usePathname: () => '/datasets' }))
vi.mock('@/lib/auth-headers', () => ({ getAuthHeaders: () => ({ Authorization: 'Bearer token' }) }))
vi.mock('@/lib/api', () => ({ observabilityApi: { reportFrontendVital: mocks.report } }))

import { WebVitalsReporter, canReportWebVital, normalizeWebVitalMetric, shouldReportWebVital } from './web-vitals-reporter'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('web vitals policy', () => {
  afterEach(() => {
    vi.clearAllMocks()
    mocks.callback = undefined
    document.body.replaceChildren()
  })

  it('accepts supported metrics and authenticated non-auth pages', () => {
    expect(shouldReportWebVital('LCP')).toBe(true)
    expect(shouldReportWebVital('TTFB')).toBe(false)
    expect(canReportWebVital('/datasets', { Authorization: 'Bearer token' })).toBe(true)
    expect(canReportWebVital('/auth/login', { Authorization: 'Bearer token' })).toBe(false)
  })

  it('normalizes optional metric fields', () => {
    expect(normalizeWebVitalMetric({ id: 'v1', name: 'INP', value: 42, rating: 'good', navigationType: 'navigate' } as never)).toEqual({
      id: 'v1',
      name: 'INP',
      value: 42,
      rating: 'good',
      navigation_type: 'navigate',
    })
  })

  it('reports each supported metric id once', async () => {
    const container = document.createElement('div')
    const root = createRoot(container)
    act(() => root.render(React.createElement(WebVitalsReporter)))

    const metric = { id: 'v1', name: 'LCP', value: 42, rating: 'good' }
    mocks.callback?.(metric)
    mocks.callback?.(metric)
    await Promise.resolve()

    expect(mocks.report).toHaveBeenCalledOnce()
    expect(mocks.report).toHaveBeenCalledWith(
      { id: 'v1', name: 'LCP', value: 42, rating: 'good', page: '/datasets' },
      { keepalive: true },
    )
    act(() => root.unmount())
  })
})
