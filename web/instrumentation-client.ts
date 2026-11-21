import { reloadOnceForStaleChunk } from '@/lib/stale-chunk-recovery'

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN
const shouldEnableSentry = process.env.NODE_ENV === 'production' && Boolean(dsn)
type RouterTransitionArgs = [href: string, navigationType: string]
type StaleChunkRecoveryGlobal = typeof globalThis & {
  __mimirqStaleChunkRecoveryInstalled__?: boolean
}

let sentryModulePromise: Promise<typeof import('@sentry/nextjs') | null> | null = null

function installStaleChunkRecovery() {
  if (globalThis.window === undefined) return

  const runtime = globalThis as StaleChunkRecoveryGlobal
  if (runtime.__mimirqStaleChunkRecoveryInstalled__) return
  runtime.__mimirqStaleChunkRecoveryInstalled__ = true

  globalThis.window.addEventListener('error', (event) => {
    const error = event.error ?? event.message
    if (reloadOnceForStaleChunk(error)) event.preventDefault()
  })

  globalThis.window.addEventListener('unhandledrejection', (event) => {
    if (reloadOnceForStaleChunk(event.reason)) event.preventDefault()
  })
}

installStaleChunkRecovery()

function loadSentryModule() {
  sentryModulePromise ??= import('@sentry/nextjs')
    .then((Sentry) => {
      Sentry.init({
        dsn,
        tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? 0),
        sendDefaultPii: false,
      })
      return Sentry
    })
    .catch(() => null)
  return sentryModulePromise
}

export function onRouterTransitionStart(...args: RouterTransitionArgs) {
  if (!shouldEnableSentry) return
  void loadSentryModule().then((Sentry) => {
    if (!Sentry) return
    try {
      Sentry.captureRouterTransitionStart(...args)
    } catch {
      // ignore best-effort telemetry failures
    }
  })
}
