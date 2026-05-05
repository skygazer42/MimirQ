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
      review_signals: {
        basis: 'all',
        short_indices: [1],
        duplicate_indices: [0, 1],
        gap_indices: [2],
        overlap_indices: [],
        gap_before_by_index: { 2: 50 },
        overlap_prev_by_index: {},
      },
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
    expect(out.review_signals.short_indices).toEqual([1])
    expect(out.review_signals.duplicate_indices).toEqual(expect.arrayContaining([0, 1]))
    expect(out.review_signals.gap_indices).toEqual(expect.arrayContaining([2]))
    expect(out.summary.issue_counts).toEqual({ short: 1, duplicate: 2, gap: 1, overlap: 0 })
  })

  it('does not invent review signals when backend omits them', () => {
    const preview: any = {
      filename: 'demo.pdf',
      file_type: 'pdf',
      file_size: 123,
      total_chunks: 2,
      total_characters: 400,
      params: { chunk_size: 100, chunk_overlap: 10, unit: 'chars' },
      parser_backend: 'auto',
      chunk_strategy: 'langchain_recursive',
      stats: { count: 2, unit: 'chars' },
      chunks: [
        { index: 0, content: 'same', length: 4, start_index: 0, end_index: 4 },
        { index: 1, content: 'same', length: 4, start_index: 100, end_index: 104 },
      ],
    }

    const out = chunkPreviewToReviewReport(preview, {}, { include_disabled: false }) as any
    expect(out.review_signals).toEqual({
      basis: 'all',
      short_indices: [],
      duplicate_indices: [],
      gap_indices: [],
      overlap_indices: [],
      gap_before_by_index: {},
      overlap_prev_by_index: {},
    })
    expect(out.summary.issue_counts).toEqual({ short: 0, duplicate: 0, gap: 0, overlap: 0 })
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
      review_signals: {
        basis: 'all',
        short_indices: [],
        duplicate_indices: [],
        gap_indices: [1],
        overlap_indices: [],
        gap_before_by_index: { 1: 20 },
        overlap_prev_by_index: {},
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
