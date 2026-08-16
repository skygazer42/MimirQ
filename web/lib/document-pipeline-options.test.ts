import { describe, expect, it } from 'vitest'

import { normalizeDocumentPipelineOptions } from './document-pipeline-options'

describe('normalizeDocumentPipelineOptions', () => {
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
