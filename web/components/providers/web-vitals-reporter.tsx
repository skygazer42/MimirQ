'use client'

import { useCallback, useEffect, useRef } from 'react'
import { useReportWebVitals } from 'next/web-vitals'

import { usePathname } from '@/i18n/navigation'
import { getAuthHeaders } from '@/lib/auth-headers'
import { observabilityApi, type FrontendWebVitalReportRequest } from '@/lib/api/observability'
import { reportClientWarning } from '@/lib/client-logging'

type FrontendWebVitalName = FrontendWebVitalReportRequest['name']

type WebVitalMetric = Readonly<{
  id: string
  name: string
  value: number
  rating: string
  navigationType: string
}>

const TRACKED_WEB_VITALS = new Set<string>(['LCP', 'CLS', 'FID', 'INP'])

export function shouldReportWebVital(name: string): name is FrontendWebVitalName {
  return TRACKED_WEB_VITALS.has(name)
}

export function canReportWebVital(pathname: string, authHeaders: Readonly<Record<string, string>>): boolean {
  if (pathname.startsWith('/auth')) {
    return false
  }
  return Boolean(authHeaders.Authorization || authHeaders['X-User-ID'])
}

export function WebVitalsReporter() {
  const sentMetricIdsRef = useRef<Set<string>>(new Set())
  const pathname = usePathname()
  const pathnameRef = useRef(pathname)

  useEffect(() => {
    pathnameRef.current = pathname
  }, [pathname])

  const reportWebVital = useCallback((metric: WebVitalMetric) => {
    if (!shouldReportWebVital(metric.name)) return
    const authHeaders = getAuthHeaders()
    if (!canReportWebVital(pathnameRef.current, authHeaders)) return
    if (sentMetricIdsRef.current.has(metric.id)) return

    sentMetricIdsRef.current.add(metric.id)

    const request: FrontendWebVitalReportRequest = {
      id: metric.id,
      name: metric.name,
      value: metric.value,
      rating: metric.rating,
      navigation_type: metric.navigationType,
      page: pathnameRef.current,
    }

    void observabilityApi.reportFrontendVital(request, { keepalive: true }).catch((error) => {
      reportClientWarning('Failed to report web vital', error)
    })
  }, [])

  useReportWebVitals(reportWebVital)

  return null
}
