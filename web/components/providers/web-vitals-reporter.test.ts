import { describe, expect, it } from 'vitest'

import { normalizeWebVitalMetric, shouldReportWebVital } from './web-vitals-reporter'

describe('web-vitals-reporter helpers', () => {
  it('tracks only vitals relevant to the resilience plan', () => {
    expect(shouldReportWebVital('LCP')).toBe(true)
    expect(shouldReportWebVital('FID')).toBe(true)
    expect(shouldReportWebVital('INP')).toBe(true)
    expect(shouldReportWebVital('CLS')).toBe(false)
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
})
