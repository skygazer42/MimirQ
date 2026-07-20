// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ServiceWorkerRegistrar,
  clearLocalMimirqCaches,
  shouldClearLocalServiceWorker,
  shouldRegisterServiceWorker,
} from './service-worker-registrar'

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('service worker policy', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    document.body.replaceChildren()
  })

  it('registers only on secure non-local origins', () => {
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'app.example.com', protocol: 'https:' })).toBe(true)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'localhost', protocol: 'https:' })).toBe(false)
    expect(shouldRegisterServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'app.example.com', protocol: 'http:' })).toBe(false)
  })

  it('clears stale workers only on local hosts', () => {
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: '[::1]' })).toBe(true)
    expect(shouldClearLocalServiceWorker({ hasWindow: true, hasServiceWorker: true, hostname: 'app.example.com' })).toBe(false)
  })

  it('deletes only MimirQ caches', async () => {
    const deleteCache = vi.fn().mockResolvedValue(true)
    vi.stubGlobal('caches', {
      keys: vi.fn().mockResolvedValue(['mimirq-v1', 'other-app']),
      delete: deleteCache,
    })

    await clearLocalMimirqCaches()
    expect(deleteCache).toHaveBeenCalledOnce()
    expect(deleteCache).toHaveBeenCalledWith('mimirq-v1')
  })

  it('unregisters stale local workers when mounted on localhost', async () => {
    const unregister = vi.fn().mockResolvedValue(true)
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: vi.fn().mockResolvedValue([{ unregister }]) },
    })
    vi.stubGlobal('caches', { keys: vi.fn().mockResolvedValue([]), delete: vi.fn() })
    const container = document.createElement('div')
    const root = createRoot(container)

    await act(async () => root.render(React.createElement(ServiceWorkerRegistrar)))
    expect(unregister).toHaveBeenCalledOnce()
    act(() => root.unmount())
  })
})
