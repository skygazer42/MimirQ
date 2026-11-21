'use client'

import { useEffect } from 'react'
import { reportClientWarning } from '@/lib/client-logging'

type RegistrationEnv = {
  hasWindow: boolean
  hasServiceWorker: boolean
  hostname: string
  protocol?: string
  isSecureContext?: boolean
}

export const LOCAL_SERVICE_WORKER_CLEANUP_RETRY_DELAYS_MS = [1000, 3000] as const

function normalizeHostname(hostname: string): string {
  return hostname
    .trim()
    .toLowerCase()
    .replace(/^\[(.*)\]$/, '$1')
}

function isLocalhostHostname(hostname: string): boolean {
  const normalized = normalizeHostname(hostname)
  return normalized === 'localhost' || normalized === '127.0.0.1' || normalized === '::1'
}

export function shouldRegisterServiceWorker(env: RegistrationEnv): boolean {
  if (!env.hasWindow || !env.hasServiceWorker) return false
  const hostname = normalizeHostname(env.hostname)
  if (!hostname) return false
  if (isLocalhostHostname(hostname)) return false
  const protocol = env.protocol?.trim().toLowerCase()
  if (protocol && protocol !== 'https:') return false
  if (env.isSecureContext === false) return false
  return true
}

export function shouldClearLocalServiceWorker(env: RegistrationEnv): boolean {
  return env.hasWindow && env.hasServiceWorker && isLocalhostHostname(env.hostname)
}

export async function clearLocalMimirqCaches() {
  if (typeof caches === 'undefined') return

  const keys = await caches.keys()
  await Promise.all(keys.filter((key) => key.startsWith('mimirq-')).map((key) => caches.delete(key)))
}

async function clearLocalMimirqServiceWorkerState() {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return

  const registrations = await navigator.serviceWorker.getRegistrations()
  await Promise.all(registrations.map((registration) => registration.unregister()))

  await clearLocalMimirqCaches()
}

function reportServiceWorkerCleanupFailure(error: unknown) {
  reportClientWarning('Service worker cleanup failed', error)
}

function scheduleLocalMimirqServiceWorkerCleanup() {
  const runCleanup = () => {
    clearLocalMimirqServiceWorkerState().catch(reportServiceWorkerCleanupFailure)
  }

  runCleanup()

  const timers = LOCAL_SERVICE_WORKER_CLEANUP_RETRY_DELAYS_MS.map((delay) => globalThis.setTimeout(runCleanup, delay))
  return () => {
    timers.forEach((timer) => globalThis.clearTimeout(timer))
  }
}

export function ServiceWorkerRegistrar() {
  useEffect(() => {
    const env = {
      hasWindow: true,
      hasServiceWorker: 'serviceWorker' in navigator,
      hostname: window.location.hostname,
      protocol: window.location.protocol,
      isSecureContext: window.isSecureContext,
    }
    const enabled = shouldRegisterServiceWorker(env)
    if (!enabled) {
      if (shouldClearLocalServiceWorker(env)) {
        return scheduleLocalMimirqServiceWorkerCleanup()
      }
      return
    }

    navigator.serviceWorker.register('/sw.js').catch((error) => {
      reportClientWarning('Service worker registration failed', error)
    })
  }, [])

  return null
}
