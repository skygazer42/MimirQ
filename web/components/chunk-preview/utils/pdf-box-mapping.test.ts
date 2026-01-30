import { describe, expect, it } from 'vitest'
import { buildBlockIdToBestChunkIndex } from './pdf-box-mapping'

describe('pdf-box-mapping', () => {
  it('maps block id to the chunk with max overlap (ties -> smaller chunk)', () => {
    const chunks = [
      { start_index: 0, end_index: 100 }, // len 100
      { start_index: 50, end_index: 120 }, // len 70 (smaller)
      { start_index: 120, end_index: 200 },
    ]

    const blocks = [
      { id: 'b1', start: 60, end: 90 }, // overlaps chunk0=30, chunk1=30 -> choose chunk1 (smaller)
      { id: 'b2', start: 145, end: 160 }, // overlaps chunk2 only
    ]

    const map = buildBlockIdToBestChunkIndex(blocks, chunks)
    expect(map.get('b1')).toBe(1)
    expect(map.get('b2')).toBe(2)
  })

  it('skips invalid ranges', () => {
    const chunks = [
      { start_index: 0, end_index: 10 },
      { start_index: 10, end_index: 20 },
    ]
    const blocks = [
      { id: 'bad1', start: 5, end: 5 }, // empty
      { id: 'bad2', start: 20, end: 10 }, // reversed -> treated as empty
      { id: 'ok', start: 11, end: 12 },
    ]
    const map = buildBlockIdToBestChunkIndex(blocks, chunks)
    expect(map.has('bad1')).toBe(false)
    expect(map.has('bad2')).toBe(false)
    expect(map.get('ok')).toBe(1)
  })
})

