import { describe, expect, it } from 'vitest'
import type { ChunkPreviewItem } from '@/types'
import type { ChunkSearchResult } from './retrieval-search'
import { computeRerankSimScore, rerankChunkSearchResults } from './reranker-sim'

function chunk(index: number, content: string): ChunkPreviewItem {
  return {
    index,
    content,
    length: content.length,
    tokens_est: Math.max(1, Math.ceil(content.length / 4)),
    start_index: 0,
    end_index: content.length,
    page_number: 1,
    metadata: {},
  }
}

describe('reranker-sim', () => {
  it('scores higher when query tokens appear in content', () => {
    const q = 'alpha beta'
    const good = computeRerankSimScore(q, '... alpha ... beta ...')
    const bad = computeRerankSimScore(q, '... alpha ...')
    expect(good).toBeGreaterThan(bad)
  })

  it('reranks results by combined score', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 'this has alpha and beta'),
      chunk(1, 'this has alpha only'),
    ]

    const retrieval: ChunkSearchResult[] = [
      { index: 1, score: 10, snippet: 'alpha', page_number: 1, section: undefined },
      { index: 0, score: 9, snippet: 'alpha beta', page_number: 1, section: undefined },
    ]

    const reranked = rerankChunkSearchResults(retrieval, 'alpha beta', chunks, { alpha: 0.4 })
    expect(reranked).toHaveLength(2)
    expect(reranked[0].index).toBe(0)
    expect(reranked[0].combined_score).toBeGreaterThan(0)
    expect(reranked[0].retrieval_score).toBe(9)
  })
})

