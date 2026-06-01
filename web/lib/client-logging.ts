import * as Sentry from '@sentry/browser'

type ClientLogOptions = Readonly<{
  level?: 'error' | 'warning' | 'info'
  tags?: Record<string, string>
}>

function asError(message: string, cause: unknown): Error {
  if (cause instanceof Error) return cause
  return new Error(message, { cause })
}

export function reportClientError(message: string, cause: unknown, options: ClientLogOptions = {}): void {
  Sentry.withScope((scope) => {
    scope.setLevel(options.level || 'error')
    for (const [key, value] of Object.entries(options.tags || {})) {
      if (value) scope.setTag(key, value)
    }
    scope.setContext('client_log', { message })
    Sentry.captureException(asError(message, cause))
  })
}

export function reportClientWarning(message: string, cause: unknown, options: ClientLogOptions = {}): void {
  reportClientError(message, cause, { ...options, level: 'warning' })
}
