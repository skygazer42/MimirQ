import { describe, expect, it } from 'vitest'

import type { ChunkPreviewResponse } from '@/types'
import {
  applyChunkOverridesToPreview,
  chunkPreviewToCsv,
  chunkPreviewToJsonl,
  chunkPreviewToMarkdown,
  toChunkPreviewExport,
} from './export'

function preview(): ChunkPreviewResponse {
  return {
    filename: 'export.md',
    file_type: 'md',
    file_size: 20,
    total_chunks: 2,
    total_chunks_full: 2,
    total_characters: 12,
    params: { chunk_size: 500, chunk_overlap: 0, unit: 'chars' },
    chunks: [
      { index: 4, content: 'first', length: 5, tokens_est: 2, start_index: 0, end_index: 5, page_number: 0 },
      {
        index: 9,
        content: 'second',
        length: 6,
        start_index: 6,
        end_index: 12,
        metadata: { weight: 0, reviewed: false },
      },
    ],
    original_text: 'first\nsecond',
    original_text_cleaned: 'first\nsecond',
    original_text_included: true,
    stats: { count: 2, avg: 6, p95: 6 },
    chunking_stats_tokens: { count: 2, avg: 2 },
    quality_gate: { grade: 'pass' },
    review_signals: { short_indices: [4] },
    recommendations: ['source recommendation'],
    recommendation_patches: [{ id: 'source', title: 'Original settings' }],
    parser_backend: 'auto',
    chunk_strategy: 'recursive',
  }
}

describe('actual preview exports', () => {
  it('omits both original text payloads and reports their absence without changing the preview', () => {
    const source = preview()
    const result = toChunkPreviewExport(source)
    expect(result).not.toHaveProperty('original_text')
    expect(result).not.toHaveProperty('original_text_cleaned')
    expect(result.original_text_included).toBe(false)
    expect(result.chunks).toEqual(source.chunks)
    expect(source.original_text_included).toBe(true)
    expect(source.original_text).toBe('first\nsecond')
  })

  it('does not claim an empty original text is included in a lightweight file', () => {
    const source = { ...preview(), original_text: '', original_text_cleaned: '' }
    expect(toChunkPreviewExport(source).original_text_included).toBe(false)
  })

  it('uses the actual chunk index and code point length, keeps absent metadata and invalidates old analysis', () => {
    const source = preview()
    const result = applyChunkOverridesToPreview(source, { 4: { content: ' 😀\n' } })
    expect(result.chunks[0]).toMatchObject({ index: 4, content: ' 😀\n', length: 3, start_index: 0, end_index: 5 })
    expect(result.chunks[0].metadata).toBeUndefined()
    expect(result.chunks[0].tokens_est).toBeUndefined()
    expect(result.stats).toBeNull()
    expect(result).not.toHaveProperty('chunking_stats_tokens')
    expect(result).not.toHaveProperty('quality_gate')
    expect(result).not.toHaveProperty('review_signals')
    expect(result).not.toHaveProperty('recommendations')
    expect(result).not.toHaveProperty('recommendation_patches')
    expect(source.chunks[0].content).toBe('first')
    expect(source.stats).toEqual({ count: 2, avg: 6, p95: 6 })
  })

  it('preserves an explicitly cleared body and real metadata values', () => {
    const result = applyChunkOverridesToPreview(preview(), {
      4: { content: '', metadata: { weight: 0, reviewed: false, label: '' } },
    })
    expect(result.chunks[0]).toMatchObject({
      content: '',
      length: 0,
      metadata: { weight: 0, reviewed: false, label: '' },
    })
    expect(result.stats).toBeNull()
  })

  it('exports only enabled chunks without retaining measurements for the removed scope', () => {
    const source = preview()
    const result = applyChunkOverridesToPreview(source, { 4: { disabled: true } })
    expect(result.chunks.map((chunk) => chunk.index)).toEqual([9])
    expect(result.total_chunks).toBe(1)
    expect(result.stats).toBeNull()
    expect(result).not.toHaveProperty('total_chunks_full')
    expect(source.total_chunks).toBe(2)
  })

  it('keeps included disabled chunks marked while preserving known zero tokens and original source ranges', () => {
    const source = preview()
    source.chunks[0].tokens_est = 0
    const result = applyChunkOverridesToPreview(source, { 4: { disabled: true } }, { include_disabled: true })
    expect(result.chunks[0]).toMatchObject({
      index: 4,
      tokens_est: 0,
      start_index: 0,
      end_index: 5,
      metadata: { __mimirq_skip: true },
    })
    expect(result.total_chunks).toBe(2)
    expect(source.chunks[0].metadata).toBeUndefined()
  })

  it('retains the original response for no effective edit or an override outside the current returned chunks', () => {
    const source = preview()
    expect(applyChunkOverridesToPreview(source, {})).toBe(source)
    expect(applyChunkOverridesToPreview(source, { 99: { disabled: true } })).toBe(source)
    expect(applyChunkOverridesToPreview(source, { 4: { content: 'first', disabled: false } })).toBe(source)
  })

  it('does not attach source aggregate decisions to edited hierarchy metadata', () => {
    const result = applyChunkOverridesToPreview(preview(), { 9: { metadata: { chunk_role: 'parent' } } })
    expect(result.chunks[1].metadata).toEqual({ chunk_role: 'parent' })
    expect(result.stats).toBeNull()
    expect(result).not.toHaveProperty('quality_gate')
  })

  it('escapes real CSV fields without losing page zero, an empty body or source newlines', () => {
    const source = preview()
    source.chunks[0].content = 'a,"b"\r\n😀'
    source.chunks[1].content = ''
    expect(chunkPreviewToCsv(source)).toBe(
      'index,page_number,start_index,end_index,length,content\n4,0,0,5,5,"a,""b""\r\n😀"\n9,,6,12,6,',
    )
  })

  it('keeps JSONL optional fields absent and preserves known zero, false and empty content', () => {
    const source = preview()
    source.chunks[0].tokens_est = 0
    source.chunks[1].content = ''
    const result = chunkPreviewToJsonl(source)
      .split('\n')
      .map((row) => JSON.parse(row))
    expect(result[0]).toMatchObject({ page_number: 0, tokens_est: 0 })
    expect(result[0]).not.toHaveProperty('metadata')
    expect(result[1]).not.toHaveProperty('page_number')
    expect(result[1]).not.toHaveProperty('tokens_est')
    expect(result[1]).toMatchObject({ content: '', metadata: { weight: 0, reviewed: false } })
  })

  it('uses a Markdown fence that cannot be closed by the actual body and keeps real page and token zero', () => {
    const source = preview()
    source.chunks[0].content = 'before\n````\n😀after'
    source.chunks[0].tokens_est = 0
    const result = chunkPreviewToMarkdown(source)
    expect(result).toContain('## Chunk 5 (P.0)')
    expect(result).toContain('- length: 5 chars · 0 tok')
    expect(result).toContain('`````text\nbefore\n````\n😀after\n`````')
  })
})
