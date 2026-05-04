import { describe, expect, it } from 'vitest'

import type { ChunkPreviewItem } from '@/types'
import { chunkIsReviewed, chunkNeedsReview } from './metadata'

function chunk(metadata: Record<string, unknown>): ChunkPreviewItem {
  return {
    index: 0,
    content: 'chunk',
    length: 5,
    tokens_est: 2,
    start_index: 0,
    end_index: 5,
    page_number: 1,
    metadata,
  }
}

describe('chunk metadata review state', () => {
  it('treats explicit review approval as no longer needing review', () => {
    const item = chunk({
      needs_review: true,
      review_status: 'approved',
      reviewed: true,
      semantic_quality: { needs_review: true },
    })

    expect(chunkIsReviewed(item)).toBe(true)
    expect(chunkNeedsReview(item)).toBe(false)
  })

  it('falls back to semantic quality review hints when not approved', () => {
    const item = chunk({
      semantic_quality: { needs_review: true },
    })

    expect(chunkIsReviewed(item)).toBe(false)
    expect(chunkNeedsReview(item)).toBe(true)
  })
})
