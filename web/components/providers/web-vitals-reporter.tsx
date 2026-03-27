'use client'

import { useRef } from 'react'
import { usePathname } from 'next/navigation'
import { useReportWebVitals } from 'next/web-vitals'

import { getAuthHeaders } from '@/lib/auth-headers'
import { observabilityApi } from '@/lib/api'

export type FrontendWebVitalName = 'LCP' | 'CLS' | 'FID' | 'INP'

export type FrontendWebVitalPayload = Readonly<{
  id: string
  name: FrontendWebVitalName
  value: number
  rating?: string
  navigation_type?: string
  page?: string
}>

const TRACKED_WEB_VITALS = new Set<FrontendWebVitalName>(['LCP', 'CLS', 'FID', 'INP'])
type WebVitalMetric = Parameters<typeof useReportWebVitals>[0] extends (metric: infer T) => void ? T : never

export function shouldReportWebVital(name: string): name is FrontendWebVitalName {
  return TRACKED_WEB_VITALS.has(name as FrontendWebVitalName)
}

export function normalizeWebVitalMetric(metric: WebVitalMetric): FrontendWebVitalPayload {
  const payload: FrontendWebVitalPayload = {
    id: String(metric.id || ''),
    name: metric.name as FrontendWebVitalName,
    value: Number(metric.value),
  }

  if (typeof metric.rating === 'string' && metric.rating) {
    ;(payload as { rating?: string }).rating = metric.rating
  }
  if (typeof metric.navigationType === 'string' && metric.navigationType) {
    ;(payload as { navigation_type?: string }).navigation_type = metric.navigationType
  }

  return payload
}

export function canReportWebVital(
  pathname: string | null | undefined,
  authHeaders: Readonly<Record<string, string>>
): boolean {
  if (typeof pathname === 'string' && pathname.startsWith('/auth')) {
    return false
  }
  return Boolean(authHeaders.Authorization || authHeaders['X-User-ID'])
}

export function WebVitalsReporter() {
  const sentMetricIdsRef = useRef<Set<string>>(new Set())
  const pathname = usePathname()

  useReportWebVitals((metric) => {
    if (!shouldReportWebVital(metric.name)) return
    const authHeaders = getAuthHeaders()
    if (!canReportWebVital(pathname, authHeaders)) return
    if (sentMetricIdsRef.current.has(metric.id)) return

    sentMetricIdsRef.current.add(metric.id)

    const payload = normalizeWebVitalMetric(metric)
    const page = pathname || globalThis.window?.location?.pathname
    const request = page ? { ...payload, page } : payload

    void observabilityApi.reportFrontendVital(request, { keepalive: true }).catch((error) => {
      console.warn('Failed to report web vital', error)
    })
  })

  return null
}
