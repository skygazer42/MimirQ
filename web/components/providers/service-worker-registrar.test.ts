import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  LOCAL_SERVICE_WORKER_CLEANUP_RETRY_DELAYS_MS,
  clearLocalMimirqServiceWorkerState,
  shouldClearLocalServiceWorker,
  shouldRegisterServiceWorker,
} from './service-worker-registrar'

const originalNavigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
const originalCachesDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'caches')

describe('service-worker-registrar helpers', () => {
  afterEach(() => {
    if (originalNavigatorDescriptor) {
      Object.defineProperty(globalThis, 'navigator', originalNavigatorDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'navigator')
    }
    if (originalCachesDescriptor) {
      Object.defineProperty(globalThis, 'caches', originalCachesDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'caches')
    }
    vi.restoreAllMocks()
  })

  it('registers only in supported browser production contexts', () => {
    expect(
      shouldRegisterServiceWorker({
        hasWindow: true,
        hasServiceWorker: true,
        hostname: 'mimirq.example',
        protocol: 'https:',
        isSecureContext: true,
      })
    ).toBe(true)
    expect(
      shouldRegisterServiceWorker({
        hasWindow: true,
        hasServiceWorker: true,
        hostname: 'mimirq.example',
        protocol: 'http:',
        isSecureContext: false,
      })
    ).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: false, hostname: 'mimirq.example' })).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: false, hasServiceWorker: true, hostname: 'mimirq.example' })).toBe(false)
  })

  it('skips service-worker registration on localhost opt-out contexts', () => {
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'localhost' })).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '127.0.0.1' })).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '::1' })).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '[::1]' })).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '  ' })).toBe(false)
  })

  it('clears stale localhost registrations left by older builds', () => {
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'localhost' })).toBe(true)
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '127.0.0.1' })).toBe(true)
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '[::1]' })).toBe(true)
    expect(shouldClearLocalServiceWorker({ hasWindow: false, hasServiceWorker: true, hostname: 'localhost' })).toBe(false)
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: false, hostname: 'localhost' })).toBe(false)
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'mimirq.example' })).toBe(false)
  })

  it('retries local cleanup after old service workers finish late cache writes', () => {
    expect(LOCAL_SERVICE_WORKER_CLEANUP_RETRY_DELAYS_MS.length).toBeGreaterThan(0)
    expect([...LOCAL_SERVICE_WORKER_CLEANUP_RETRY_DELAYS_MS]).toEqual(
      [...LOCAL_SERVICE_WORKER_CLEANUP_RETRY_DELAYS_MS].sort((a, b) => a - b)
    )
  })

  it('unregisters local service workers and deletes only mimirq caches', async () => {
    const unregisterFirst = vi.fn().mockResolvedValue(true)
    const unregisterSecond = vi.fn().mockResolvedValue(true)
    const deleteCache = vi.fn().mockResolvedValue(true)
    const getRegistrations = vi.fn().mockResolvedValue([{ unregister: unregisterFirst }, { unregister: unregisterSecond }])
    const keys = vi.fn().mockResolvedValue(['mimirq-static-v4', 'other-app-cache', 'mimirq-app-shell-v4'])

    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      value: { serviceWorker: { getRegistrations } },
    })
    Object.defineProperty(globalThis, 'caches', {
      configurable: true,
      value: { delete: deleteCache, keys },
    })

    await clearLocalMimirqServiceWorkerState()

    expect(getRegistrations).toHaveBeenCalledTimes(1)
    expect(unregisterFirst).toHaveBeenCalledTimes(1)
    expect(unregisterSecond).toHaveBeenCalledTimes(1)
    expect(keys).toHaveBeenCalledTimes(1)
    expect(deleteCache).toHaveBeenCalledTimes(2)
    expect(deleteCache).toHaveBeenCalledWith('mimirq-static-v4')
    expect(deleteCache).toHaveBeenCalledWith('mimirq-app-shell-v4')
    expect(deleteCache).not.toHaveBeenCalledWith('other-app-cache')
  })
})
