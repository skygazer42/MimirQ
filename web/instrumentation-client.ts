const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN
const shouldEnableSentry = process.env.NODE_ENV === 'production' && Boolean(dsn)
type RouterTransitionArgs = [href: string, navigationType: string]

let sentryModulePromise: Promise<typeof import('@sentry/nextjs') | null> | null = null
let sentryInitialized = false

async function loadSentryModule() {
  if (!shouldEnableSentry) return null
  if (!sentryModulePromise) {
    sentryModulePromise = import('@sentry/nextjs')
      .then((Sentry) => {
        if (!sentryInitialized) {
          Sentry.init({
            dsn,
            tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE || 0),
            sendDefaultPii: false,
          })
          sentryInitialized = true
        }
        return Sentry
      })
      .catch(() => null)
  }
  return sentryModulePromise
}

export const onRouterTransitionStart = (...args: RouterTransitionArgs) => {
  if (!shouldEnableSentry) return undefined
  void loadSentryModule().then((Sentry) => {
    if (!Sentry) return
    try {
      Sentry.captureRouterTransitionStart(...args)
    } catch {
      // ignore best-effort telemetry failures
    }
  })
  return undefined
}
