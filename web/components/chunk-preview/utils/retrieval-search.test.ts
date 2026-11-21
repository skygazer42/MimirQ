import { describe, expect, it } from 'vitest'

import type { ChunkPreviewItem } from '@/types'
import { buildChunkSearchIndex, searchChunkIndex } from './retrieval-search'
import { rerankChunkSearchResults } from './reranker-sim'

function chunk(index: number, content: string): ChunkPreviewItem {
  const length = Array.from(content).length
  return { index, content, length, start_index: 0, end_index: length, page_number: 0 }
}

describe('actual local chunk search and rank scope', () => {
  it('keeps actual backend indices, page zero and scores from the installed search implementation', () => {
    const source = [chunk(4, 'needle first'), chunk(9, 'second paragraph')]
    const index = buildChunkSearchIndex(source)
    const results = searchChunkIndex(index, 'needle')
    expect(results).toHaveLength(1)
    expect(results[0]).toMatchObject({ index: 4, page_number: 0, snippet: 'needle first' })
    expect(results[0].score).toBeGreaterThan(0)
    expect(source[0].content).toBe('needle first')
  })

  it('keeps whole source characters in a leading snippet for a fuzzy hit', () => {
    const content = `${'a '.repeat(69)}a😀 fuzxy`
    const results = searchChunkIndex(buildChunkSearchIndex([chunk(4, content)]), 'fuzzy')
    expect(results).toHaveLength(1)
    expect(results[0].snippet).toContain('😀')
  })

  it('does not invent an empty body when a ranked result belongs to another chunk snapshot', () => {
    expect(() =>
      rerankChunkSearchResults([{ index: 99, score: 1, snippet: 'old' }], 'needle', [chunk(4, 'needle')]),
    ).toThrow(/99/)
  })

  it('preserves real zero weights and scores and keeps input ranking unmodified', () => {
    const source = [chunk(4, 'needle'), chunk(9, 'other')]
    const results = [
      { index: 9, score: 10, snippet: 'other' },
      { index: 4, score: 0, snippet: 'needle' },
    ]
    expect(rerankChunkSearchResults(results, 'needle', source, { alpha: 0 }).map((result) => result.index)).toEqual([
      4, 9,
    ])
    expect(rerankChunkSearchResults(results, 'needle', source, { alpha: 1 }).map((result) => result.index)).toEqual([
      9, 4,
    ])
    expect(results[1].score).toBe(0)
    expect(results.map((result) => result.index)).toEqual([9, 4])
  })

  it('exposes an invalid weight instead of silently replacing it with zero', () => {
    expect(() =>
      rerankChunkSearchResults([{ index: 4, score: 1, snippet: 'needle' }], 'needle', [chunk(4, 'needle')], {
        alpha: Number.NaN,
      }),
    ).toThrow()
  })
})
