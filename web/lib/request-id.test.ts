import { describe, expect, it, vi } from 'vitest'

import { generateRequestId } from './request-id'

describe('generateRequestId', () => {
  it('generates a non-empty id', () => {
    const id = generateRequestId()
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(8)
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

