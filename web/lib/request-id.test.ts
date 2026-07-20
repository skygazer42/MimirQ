import { afterEach, describe, expect, it, vi } from 'vitest'

import { generateRequestId } from './request-id'

describe('generateRequestId', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('returns non-empty correlation ids without collisions', () => {
    const first = generateRequestId()
    const second = generateRequestId()
    expect(first).toBeTruthy()
    expect(second).not.toBe(first)
  })

  it('uses random values when randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (values: Uint32Array) => values.set([1, 2]),
    })
    expect(generateRequestId()).toBe('00000001-00000002')
  })

  it('falls back to a monotonic id without Web Crypto', () => {
    vi.stubGlobal('crypto', undefined)
    vi.spyOn(Date, 'now').mockReturnValue(255)
    expect(generateRequestId()).toMatch(/^ff-[0-9a-f]{8}$/)
  })
})
