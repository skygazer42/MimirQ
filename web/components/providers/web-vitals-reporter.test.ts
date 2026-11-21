// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  callback: undefined as ((metric: Record<string, unknown>) => void) | undefined,
  pathname: '/datasets',
  report: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('next/web-vitals', () => ({
  useReportWebVitals: (callback: (metric: Record<string, unknown>) => void) => {
    mocks.callback = callback
  },
}))
vi.mock('@/i18n/navigation', () => ({ usePathname: () => mocks.pathname }))
vi.mock('@/lib/auth-headers', () => ({ getAuthHeaders: () => ({ Authorization: 'Bearer token' }) }))
vi.mock('@/lib/api/observability', () => ({ observabilityApi: { reportFrontendVital: mocks.report } }))

import { WebVitalsReporter, canReportWebVital, shouldReportWebVital } from './web-vitals-reporter'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('web vitals policy', () => {
  beforeEach(() => {
    mocks.pathname = '/datasets'
  })

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
    expect(canReportWebVital('/datasets', {})).toBe(false)
  })

  it('reports each supported metric id once', async () => {
    const container = document.createElement('div')
    const root = createRoot(container)
    act(() => root.render(React.createElement(WebVitalsReporter)))

    const metric = { id: 'v1', name: 'LCP', value: 42, rating: 'good', navigationType: 'navigate' }
    mocks.callback?.(metric)
    mocks.callback?.(metric)
    await Promise.resolve()

    expect(mocks.report).toHaveBeenCalledOnce()
    expect(mocks.report).toHaveBeenCalledWith(
      { id: 'v1', name: 'LCP', value: 42, rating: 'good', navigation_type: 'navigate', page: '/datasets' },
      { keepalive: true },
    )
    act(() => root.unmount())
  })

  it('keeps one collector callback while reading the current route and skipping auth pages', async () => {
    const container = document.createElement('div')
    const root = createRoot(container)
    act(() => root.render(React.createElement(WebVitalsReporter)))
    const callback = mocks.callback!

    mocks.pathname = '/history'
    act(() => root.render(React.createElement(WebVitalsReporter)))
    expect(mocks.callback).toBe(callback)

    callback({ id: 'route-change', name: 'INP', value: 0, rating: 'good', navigationType: 'navigate' })
    await Promise.resolve()
    expect(mocks.report).toHaveBeenLastCalledWith(
      { id: 'route-change', name: 'INP', value: 0, rating: 'good', navigation_type: 'navigate', page: '/history' },
      { keepalive: true },
    )

    mocks.pathname = '/auth/login'
    act(() => root.render(React.createElement(WebVitalsReporter)))
    expect(mocks.callback).toBe(callback)
    callback({ id: 'auth-page', name: 'LCP', value: 42, rating: 'good', navigationType: 'navigate' })
    await Promise.resolve()
    expect(mocks.report).toHaveBeenCalledOnce()
    act(() => root.unmount())
  })
})
