import { describe, expect, it } from 'vitest'

import { chunkPreviewToReviewReport } from './export'

describe('chunkPreviewToReviewReport', () => {
  it('includes stats + review_signals in report', () => {
    const preview: any = {
      filename: 'demo.pdf',
      file_type: 'pdf',
      file_size: 123,
      total_chunks: 3,
      total_characters: 400,
      params: { chunk_size: 100, chunk_overlap: 10, unit: 'chars' },
      parser_backend: 'auto',
      chunk_strategy: 'langchain_recursive',
      stats: { count: 3, unit: 'chars' },
      chunks: [
        { index: 0, content: 'a'.repeat(50), length: 50, start_index: 0, end_index: 50 },
        { index: 1, content: 'a'.repeat(50), length: 50, start_index: 50, end_index: 100 },
        { index: 2, content: 'b'.repeat(200), length: 200, start_index: 150, end_index: 350 },
      ],
    }

    const out = chunkPreviewToReviewReport(preview, {}, { include_disabled: false }) as any
    expect(out.schema).toBe('mimirq.chunk_review.v1')
    expect(out.stats).toBeTruthy()
    expect(out.review_signals).toBeTruthy()
    expect(out.review_signals.short_indices).toEqual(expect.arrayContaining([0, 1]))
    expect(out.review_signals.duplicate_indices).toEqual(expect.arrayContaining([0, 1]))
    expect(out.review_signals.gap_indices).toEqual(expect.arrayContaining([2]))
  })
})

