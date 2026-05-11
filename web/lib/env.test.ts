import { describe, expect, it, vi } from 'vitest'

describe('env', () => {
  it('prefers API_INTERNAL_URL on server (SSR)', async () => {
    const originalWindow = (globalThis as any).window
    // Ensure SSR mode.
    vi.stubGlobal('window', undefined)

    const oldPublic = process.env.NEXT_PUBLIC_API_URL
    const oldInternal = process.env.API_INTERNAL_URL
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000/'
    process.env.API_INTERNAL_URL = 'http://mimirq-api:8000/'

    vi.resetModules()
    const env = await import('./env')

    expect(env.API_BASE_URL).toBe('http://mimirq-api:8000')
    expect(env.API_V1_BASE_URL).toBe('http://mimirq-api:8000/api/v1')

    // Restore.
    process.env.NEXT_PUBLIC_API_URL = oldPublic
    process.env.API_INTERNAL_URL = oldInternal
    vi.stubGlobal('window', originalWindow)
  })

  it('rewrites loopback hosts to current page host in browser', async () => {
    const originalWindow = (globalThis as any).window
    vi.stubGlobal('window', { location: { hostname: '192.168.1.10' } })

    const oldPublic = process.env.NEXT_PUBLIC_API_URL
    const oldInternal = process.env.API_INTERNAL_URL
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000'
    process.env.API_INTERNAL_URL = ''

    vi.resetModules()
    const env = await import('./env')

    expect(env.API_BASE_URL).toBe('http://192.168.1.10:8000')

    // Restore.
    process.env.NEXT_PUBLIC_API_URL = oldPublic
    process.env.API_INTERNAL_URL = oldInternal
    vi.stubGlobal('window', originalWindow)
  })

  it('rewrites localhost API URLs to 127.0.0.1 when the page is opened on 127.0.0.1', async () => {
    const originalWindow = (globalThis as any).window
    vi.stubGlobal('window', { location: { hostname: '127.0.0.1' } })

    const oldPublic = process.env.NEXT_PUBLIC_API_URL
    const oldInternal = process.env.API_INTERNAL_URL
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000'
    process.env.API_INTERNAL_URL = ''

    vi.resetModules()
    const env = await import('./env')

    expect(env.API_BASE_URL).toBe('http://127.0.0.1:8000')

    process.env.NEXT_PUBLIC_API_URL = oldPublic
    process.env.API_INTERNAL_URL = oldInternal
    vi.stubGlobal('window', originalWindow)
  })
})
