import * as Sentry from '@sentry/browser'

import type { ApiErrorInfo } from '@/lib/api-errors'
import { toApiErrorInfo, withRequestId } from '@/lib/api-errors'

type CaptureApiErrorOptions = {
  level?: 'error' | 'warning' | 'info'
  tags?: Record<string, string>
}

export function captureApiError(
  err: unknown,
  fallbackMessage: string,
  options: CaptureApiErrorOptions = {},
): ApiErrorInfo {
  const info = toApiErrorInfo(err, fallbackMessage)
  const eventError = err instanceof Error ? err : new Error(withRequestId(info.message, info.requestId), { cause: err })

  Sentry.withScope((scope) => {
    scope.setLevel(options.level === undefined ? 'error' : options.level)
    if (info.requestId !== undefined) scope.setTag('request_id', info.requestId)
    if (info.status !== undefined) scope.setTag('http_status', String(info.status))
    if (options.tags !== undefined) {
      for (const [key, value] of Object.entries(options.tags)) scope.setTag(key, value)
    }
    Sentry.captureException(eventError)
  })

  return info
}
