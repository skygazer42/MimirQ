import { describe, expect, it, vi } from 'vitest'

import { generateRequestId } from './request-id'

describe('generateRequestId', () => {
  it('generates a non-empty id', () => {
    const id = generateRequestId()
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(8)
  })

  it('uses crypto.getRandomValues when randomUUID is not available', () => {
    const original = (globalThis as any).crypto
    const getRandomValues = vi.fn((values: Uint32Array) => {
      values[0] = 0x12345678
      values[1] = 0x9abcdef0
      return values
    })
    vi.stubGlobal('crypto', { getRandomValues })
    try {
      const id = generateRequestId()
      expect(getRandomValues).toHaveBeenCalledTimes(1)
      expect(id).toMatch(/^[0-9a-f]+-[0-9a-f]+$/i)
    } finally {
      vi.stubGlobal('crypto', original)
    }
  })

  it('falls back when crypto.randomUUID is not available', () => {
    const original = (globalThis as any).crypto
    vi.stubGlobal('crypto', {})
    try {
      const id = generateRequestId()
      expect(id).toMatch(/^[0-9a-f]+-[0-9a-f]+$/i)
    } finally {
      vi.stubGlobal('crypto', original)
    }
  })
})
