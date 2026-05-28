import fs from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { reloadOnceForStaleChunk } from './stale-chunk-recovery'

const originalWindow = (globalThis as typeof globalThis & { window?: unknown }).window

function installFakeWindow(pathname = '/settings') {
  const store = new Map<string, string>()
  const fakeWindow = {
    location: {
      pathname,
      search: '',
      reload: vi.fn(),
    },
    sessionStorage: {
      getItem: vi.fn((key: string) => store.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        store.set(key, value)
      }),
    },
  }

  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: fakeWindow,
  })

  return fakeWindow
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: originalWindow,
  })
})

describe('stale chunk recovery source', () => {
  it('recognizes Next chunk and dynamic import failures and rate-limits route reloads', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'stale-chunk-recovery.ts'),
      'utf8'
    )

    expect(src).toContain('ChunkLoadError')
    expect(src).toContain('Loading chunk [\\w-]+ failed')
    expect(src).toContain('failed to fetch dynamically imported module')
    expect(src).toContain('STALE_CHUNK_RELOAD_COOLDOWN_MS')
    expect(src).toContain('sessionStorage.getItem(storageKey)')
    expect(src).toContain('globalThis.window.location.reload()')
  })

  it('suppresses immediate reload loops for the same stale settings chunk', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-28T10:00:00.000Z'))
    const fakeWindow = installFakeWindow('/settings')

    expect(reloadOnceForStaleChunk(new Error('ChunkLoadError: Loading chunk app/settings/page failed'))).toBe(true)
    expect(reloadOnceForStaleChunk(new Error('ChunkLoadError: Loading chunk app/settings/page failed'))).toBe(false)
    expect(fakeWindow.location.reload).toHaveBeenCalledTimes(1)
  })

  it('allows stale settings chunks to recover again after another rebuild window', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-28T10:00:00.000Z'))
    const fakeWindow = installFakeWindow('/settings')

    expect(reloadOnceForStaleChunk(new Error('ChunkLoadError: Loading chunk app/settings/page failed'))).toBe(true)
    vi.setSystemTime(new Date('2026-05-28T10:01:00.000Z'))
    expect(reloadOnceForStaleChunk(new Error('ChunkLoadError: Loading chunk app/settings/page failed'))).toBe(true)
    expect(fakeWindow.location.reload).toHaveBeenCalledTimes(2)
  })
})
