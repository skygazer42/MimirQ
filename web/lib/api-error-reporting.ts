import * as Sentry from '@sentry/browser'

import type { ApiErrorInfo } from '@/lib/api-errors'
import { extractRequestIdFromError, toApiErrorInfo, withRequestId } from '@/lib/api-errors'

type CaptureApiErrorOptions = {
  level?: 'error' | 'warning' | 'info'
  tags?: Record<string, string>
}

export function captureApiError(err: unknown, fallbackMessage: string, options: CaptureApiErrorOptions = {}): ApiErrorInfo {
  const info = toApiErrorInfo(err, fallbackMessage)
  const requestId = info.requestId || extractRequestIdFromError(err)
  const eventError = err instanceof Error ? err : new Error(withRequestId(info.message, requestId))

  Sentry.withScope((scope) => {
    scope.setLevel(options.level || 'error')
    if (requestId) scope.setTag('request_id', requestId)
    if (typeof info.status === 'number') scope.setTag('http_status', String(info.status))
    for (const [key, value] of Object.entries(options.tags || {})) {
      if (value) scope.setTag(key, value)
    }
    Sentry.captureException(eventError)
  })

  return {
    ...info,
    requestId,
  }
}
