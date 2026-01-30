import { describe, expect, it } from 'vitest'

import { chunkPreviewToReviewMarkdown, chunkPreviewToReviewReport } from './export'

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

describe('chunkPreviewToReviewMarkdown', () => {
  it('renders a readable summary', () => {
    const preview: any = {
      filename: 'demo.pdf',
      file_type: 'pdf',
      file_size: 123,
      total_chunks: 2,
      total_characters: 200,
      params: { chunk_size: 120, chunk_overlap: 20, unit: 'chars' },
      parser_backend: 'auto',
      chunk_strategy: 'langchain_recursive',
      stats: {
        count: 2,
        unit: 'chars',
        coverage_ratio: 0.9,
        overlap_waste_ratio: 0.2,
        gap_count: 1,
        largest_gap: 20,
      },
      chunks: [
        { index: 0, content: 'a'.repeat(50), length: 50, start_index: 0, end_index: 50 },
        { index: 1, content: 'b'.repeat(60), length: 60, start_index: 70, end_index: 130 },
      ],
    }

    const md = chunkPreviewToReviewMarkdown(preview, {}, { include_disabled: false })
    expect(md).toContain('# demo.pdf')
    expect(md.toLowerCase()).toContain('chunk review')
    expect(md).toContain('coverage_ratio')
    expect(md).toContain('overlap_waste_ratio')
    expect(md).toContain('gap_count')
  })
})
