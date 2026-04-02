import { describe, expect, it, vi } from 'vitest'

vi.mock('@/i18n/navigation', () => ({
  usePathname: () => '/chat',
}))

import { canReportWebVital, normalizeWebVitalMetric, shouldReportWebVital } from './web-vitals-reporter'

describe('web-vitals-reporter helpers', () => {
  it('tracks only vitals relevant to the resilience plan', () => {
    expect(shouldReportWebVital('LCP')).toBe(true)
    expect(shouldReportWebVital('FID')).toBe(true)
    expect(shouldReportWebVital('INP')).toBe(true)
    expect(shouldReportWebVital('CLS')).toBe(true)
  })

  it('normalizes web vital payloads for transport', () => {
    expect(
      normalizeWebVitalMetric({
        id: 'metric-1',
        name: 'LCP',
        value: 1234.56,
        rating: 'good',
        navigationType: 'navigate',
      } as any)
    ).toEqual({
      id: 'metric-1',
      name: 'LCP',
      value: 1234.56,
      rating: 'good',
      navigation_type: 'navigate',
    })
  })

  it('normalizes CLS payloads without dropping the metric identity', () => {
    expect(
      normalizeWebVitalMetric({
        id: 'metric-cls',
        name: 'CLS',
        value: 0.04,
      } as any)
    ).toEqual({
      id: 'metric-cls',
      name: 'CLS',
      value: 0.04,
    })
  })

  it('skips reporting on auth routes even when credentials exist', () => {
    expect(canReportWebVital('/auth/login', { Authorization: 'Bearer token' })).toBe(false)
  })

  it('skips reporting when no auth headers are available', () => {
    expect(canReportWebVital('/chat', {})).toBe(false)
  })

  it('allows reporting when an authenticated session is present', () => {
    expect(canReportWebVital('/chat', { Authorization: 'Bearer token' })).toBe(true)
    expect(canReportWebVital('/chat', { 'X-User-ID': 'demo' })).toBe(true)
  })

  it('allows reporting when pathname is not yet resolved but credentials exist', () => {
    expect(canReportWebVital(undefined, { Authorization: 'Bearer token' })).toBe(true)
    expect(canReportWebVital(null, { 'X-User-ID': 'demo' })).toBe(true)
  })
})
