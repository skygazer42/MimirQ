import { describe, expect, it } from 'vitest'

import { shouldRegisterServiceWorker } from './service-worker-registrar'

describe('service-worker-registrar helpers', () => {
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
})
