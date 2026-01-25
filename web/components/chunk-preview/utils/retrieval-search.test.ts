import { describe, expect, it } from 'vitest'
import type { ChunkPreviewItem } from '@/types'
import { buildChunkSearchIndex, searchChunkIndex } from './retrieval-search'

function chunk(index: number, content: string, meta?: Record<string, any>): ChunkPreviewItem {
  return {
    index,
    content,
    length: content.length,
    tokens_est: Math.max(1, Math.ceil(content.length / 4)),
    start_index: 0,
    end_index: content.length,
    page_number: 1,
    metadata: meta || {},
  }
}

describe('retrieval-search', () => {
  it('returns ranked results with snippet and metadata', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 'alpha beta gamma', { outline_path_str: 'Intro / Alpha' }),
      chunk(1, 'delta epsilon', { header_path: 'Body > Delta' }),
      chunk(2, 'zeta eta theta', {}),
    ]
    const index = buildChunkSearchIndex(chunks)
    const res = searchChunkIndex(index, 'alpha')

    expect(res.length).toBeGreaterThan(0)
    expect(res[0].index).toBe(0)
    expect(res[0].snippet.toLowerCase()).toContain('alpha')
    expect(res[0].section).toBe('Intro / Alpha')
  })

  it('respects limit', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 'alpha'),
      chunk(1, 'alpha'),
      chunk(2, 'alpha'),
    ]
    const index = buildChunkSearchIndex(chunks)
    const res = searchChunkIndex(index, 'alpha', { limit: 1 })
    expect(res).toHaveLength(1)
  })

  it('snippet uses ellipsis when match is far from start', () => {
    const content = 'x'.repeat(120) + ' alpha ' + 'y'.repeat(10)
    const chunks: ChunkPreviewItem[] = [chunk(0, content)]
    const index = buildChunkSearchIndex(chunks)
    const res = searchChunkIndex(index, 'alpha')
    expect(res).toHaveLength(1)
    expect(res[0].snippet.startsWith('…')).toBe(true)
    expect(res[0].snippet.toLowerCase()).toContain('alpha')
  })
})
