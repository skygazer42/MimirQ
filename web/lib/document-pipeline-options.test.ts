import { describe, expect, it } from 'vitest'

import { getUnsupportedDocumentPipelineOptionKeys, normalizeDocumentPipelineOptions } from './document-pipeline-options'

describe('normalizeDocumentPipelineOptions', () => {
  it('drops unsupported fields while retaining valid hidden fields and explicit zero values', () => {
    const raw = {
      sparse_enabled: true,
      qdrant_collection: 'old-collection',
      reading_order_enabled: false,
      parse_fallback_min_parse_score: 0,
      governance_keywords_provider: 'hanlp',
    }
    const normalized = normalizeDocumentPipelineOptions(raw)

    expect(getUnsupportedDocumentPipelineOptionKeys(raw)).toEqual(['sparse_enabled', 'qdrant_collection'])
    expect(normalized).not.toHaveProperty('sparse_enabled')
    expect(normalized).not.toHaveProperty('qdrant_collection')
    expect(normalized.reading_order_enabled).toBe(false)
    expect(normalized.parse_fallback_min_parse_score).toBe(0)
    expect(normalized.governance_keywords_provider).toBe('hanlp')
  })

  it('preserves backend fields the UI does not explicitly model while normalizing known keys', () => {
    const normalized = normalizeDocumentPipelineOptions({
      governance_enabled: true,
      chunk_size: '1200',
      reading_order_enabled: true,
      parse_fallback_min_parse_score: 0.42,
      cross_page_merge_max_page_gap: 2,
    })

    expect(normalized.governance_enabled).toBe(true)
    expect(normalized.chunk_size).toBe(1200)
    expect(normalized.reading_order_enabled).toBe(true)
    expect(normalized.parse_fallback_min_parse_score).toBe(0.42)
    expect(normalized.cross_page_merge_max_page_gap).toBe(2)
  })
})
