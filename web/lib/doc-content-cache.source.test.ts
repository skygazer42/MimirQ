import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'
import { classifyStoragePressure, isRecordStaleByUpdatedAt } from '@/lib/doc-content-cache'

describe('doc content cache source', () => {
  it('avoids async promise executors and rejects with Error instances', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'doc-content-cache.ts'), 'utf8')

    expect(src).not.toContain('new Promise(async')
    expect(src).toContain('function toError(')
    expect(src).not.toContain('reject(req.error)')
    expect(src).not.toContain('reject(tx.error)')
  })

  it('classifies high pressure when storage usage is near quota', () => {
    const result = classifyStoragePressure({
      storageEstimate: { usage: 920, quota: 1000 },
      cacheStats: {
        content: { totalBytes: 120 },
        source: { totalBytes: 80 },
      },
    })

    expect(result.level).toBe('high')
    expect(result.storageUsageRatio).toBeCloseTo(0.92, 3)
  })

  it('classifies high pressure when cache dominates storage usage', () => {
    const result = classifyStoragePressure({
      storageEstimate: { usage: 500 * 1024 * 1024, quota: 2_000 * 1024 * 1024 },
      cacheStats: {
        content: { totalBytes: 260 * 1024 * 1024 },
        source: { totalBytes: 190 * 1024 * 1024 },
      },
    })

    expect(result.level).toBe('high')
    expect(result.cacheShareOfUsage).toBeCloseTo(0.9, 3)
  })

  it('falls back to cache-size thresholds when storage estimate is unavailable', () => {
    const moderate = classifyStoragePressure({
      storageEstimate: null,
      cacheStats: {
        content: { totalBytes: 80 * 1024 * 1024 },
        source: { totalBytes: 30 * 1024 * 1024 },
      },
    })
    const low = classifyStoragePressure({
      storageEstimate: null,
      cacheStats: {
        content: { totalBytes: 1024 },
        source: { totalBytes: 512 },
      },
    })

    expect(moderate.level).toBe('moderate')
    expect(low.level).toBe('low')
  })

  it('marks records as stale using updatedAt and staleBefore threshold', () => {
    expect(isRecordStaleByUpdatedAt(1_000, 2_000)).toBe(true)
    expect(isRecordStaleByUpdatedAt(2_000, 2_000)).toBe(false)
    expect(isRecordStaleByUpdatedAt(3_000, 2_000)).toBe(false)
    expect(isRecordStaleByUpdatedAt(undefined, 2_000)).toBe(false)
    expect(isRecordStaleByUpdatedAt(Number.NaN, 2_000)).toBe(false)
  })
})
