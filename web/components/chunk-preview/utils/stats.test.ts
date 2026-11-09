import { describe, expect, it } from 'vitest'

import { computeChunkLengthStats } from './stats'

describe('chunk length statistics', () => {
  it('uses supplied numeric lengths, derives missing lengths and counts duplicate content', () => {
    const result = computeChunkLengthStats([{ content: 'same', length: 4.9 }, { content: 'same' }, { content: 'different', length: 12 }], { shortThreshold: 5 })

    expect(result).toMatchObject({ count: 3, total: 20, min: 4, max: 12, avg: 7, median: 4, shortCount: 2, duplicateCount: 1 })
    expect(result?.histogram.reduce((sum, bin) => sum + bin.count, 0)).toBe(3)
    expect(computeChunkLengthStats([])).toBeNull()
  })
})
