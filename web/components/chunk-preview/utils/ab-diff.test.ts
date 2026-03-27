import { describe, expect, it } from 'vitest'

import { buildSemanticEvidenceHighlights, chunkPreviewDiffToExport, computeChunkPreviewDiff } from './ab-diff'

describe('computeChunkPreviewDiff', () => {
  it('computes multiset overlap + deltas', () => {
    const a: any = {
      filename: 'demo.pdf',
      file_type: 'pdf',
      file_size: 123,
      total_chunks: 2,
      total_characters: 200,
      params: { chunk_size: 120, chunk_overlap: 20, unit: 'chars' },
      parser_backend: 'auto',
      chunk_strategy: 'langchain_recursive',
      stats: { coverage_ratio: 0.8, overlap_waste_ratio: 0.1, gap_count: 1 },
      chunks: [
        { index: 0, content: 'a', length: 10, start_index: 0, end_index: 10 },
        { index: 1, content: 'b', length: 10, start_index: 10, end_index: 20 },
      ],
    }

    const b: any = {
      ...a,
      total_chunks: 3,
      stats: { coverage_ratio: 0.9, overlap_waste_ratio: 0.05, gap_count: 0 },
      chunks: [
        { index: 0, content: 'a', length: 10, start_index: 0, end_index: 10 },
        { index: 1, content: 'c', length: 10, start_index: 10, end_index: 20 },
        { index: 2, content: 'd', length: 10, start_index: 20, end_index: 30 },
      ],
    }

    const diff = computeChunkPreviewDiff(a, b)
    expect(diff.deltaCount).toBe(1)
    expect(diff.added).toBe(2)
    expect(diff.removed).toBe(1)
    expect(diff.overlap).toBeCloseTo(0.25, 6)
  })
})

describe('chunkPreviewDiffToExport', () => {
  it('wraps a stable schema payload', () => {
    const a: any = {
      filename: 'demo.pdf',
      file_type: 'pdf',
      file_size: 123,
      total_chunks: 1,
      total_characters: 100,
      params: { chunk_size: 120, chunk_overlap: 20, unit: 'chars' },
      parser_backend: 'auto',
      chunk_strategy: 'langchain_recursive',
      chunks: [{ index: 0, content: 'a', length: 10, start_index: 0, end_index: 10 }],
    }
    const b: any = { ...a, total_chunks: 2, chunks: [...a.chunks, { index: 1, content: 'b', length: 10, start_index: 10, end_index: 20 }] }

    const out: any = chunkPreviewDiffToExport(a, b)
    expect(out.schema).toBe('mimirq.chunk_preview_diff.v1')
    expect(out.baseline).toBeTruthy()
    expect(out.current).toBeTruthy()
    expect(out.diff).toBeTruthy()
  })
})

describe('buildSemanticEvidenceHighlights', () => {
  it('emphasizes distinctive evidence fragments against the closest opposite-side example', () => {
    const diff = {
      examplesAdded: [
        { example: 'policy now requires passkey sign-in for remote access', count: 1, index: 8 },
      ],
      examplesRemoved: [
        { example: 'policy now requires sms sign-in for remote access', count: 1, index: 4 },
      ],
    } as any

    const highlights = buildSemanticEvidenceHighlights(diff)

    expect(highlights.added[0]?.referenceExample).toContain('sms sign-in')
    expect(highlights.removed[0]?.referenceExample).toContain('passkey sign-in')
    expect(highlights.added[0]?.segments.some((segment) => segment.emphasis && segment.text.includes('passkey'))).toBe(
      true
    )
    expect(highlights.removed[0]?.segments.some((segment) => segment.emphasis && segment.text.includes('sms'))).toBe(
      true
    )
  })
})
