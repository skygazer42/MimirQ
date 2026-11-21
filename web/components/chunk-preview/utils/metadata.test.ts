import { describe, expect, it } from 'vitest'

import type { ChunkPreviewItem, JsonObject } from '@/types'
import {
  chunkIsReviewed,
  chunkNeedsReview,
  getChunkParentRange,
  getChunkReviewReasons,
  getChunkRole,
  isChunkOverrideDisabled,
  isChunkOverrideEdited,
  isJsonObject,
  readMetadataString,
} from './metadata'

function chunk(metadata?: JsonObject): ChunkPreviewItem {
  return { index: 0, content: 'text', length: 4, start_index: 0, end_index: 4, metadata }
}

describe('actual chunk metadata readers', () => {
  it('retains absent metadata and actual zero/false/empty values without changing the source', () => {
    expect(getChunkRole(chunk())).toBeUndefined()
    expect(getChunkReviewReasons(chunk())).toBeUndefined()
    expect(chunkIsReviewed(chunk())).toBe(false)
    expect(chunkNeedsReview(chunk())).toBe(false)
    const metadata = {
      chunk_role: ' child ',
      reviewed: false,
      weight: 0,
      semantic_quality: { needs_review: false, reasons: [] },
    }
    const item = chunk(metadata)
    expect(getChunkRole(item)).toBe('child')
    expect(getChunkReviewReasons(item)).toEqual([])
    expect(chunkNeedsReview(item)).toBe(false)
    expect(metadata).toEqual({
      chunk_role: ' child ',
      reviewed: false,
      weight: 0,
      semantic_quality: { needs_review: false, reasons: [] },
    })
  })

  it('preserves actual reason strings and ignores values that are not reason text', () => {
    expect(getChunkReviewReasons(chunk({ semantic_quality: { reasons: ['  reason\n', '', 0, false] } }))).toEqual([
      '  reason\n',
      '',
    ])
    expect(getChunkReviewReasons(chunk({ semantic_quality: [] }))).toBeUndefined()
    expect(readMetadataString(' 0 ')).toBe('0')
    expect(readMetadataString(0)).toBeUndefined()
    expect(readMetadataString(false)).toBeUndefined()
    expect(readMetadataString('   ')).toBeUndefined()
  })

  it('keeps explicit approval above independent review flags and accepts only actual boolean flags', () => {
    expect(chunkNeedsReview(chunk({ needs_review: false, semantic_quality: { needs_review: true } }))).toBe(true)
    expect(chunkNeedsReview(chunk({ needs_review: 'true' }))).toBe(false)
    expect(chunkNeedsReview(chunk({ review_status: ' APPROVED ', needs_review: true }))).toBe(false)
    expect(chunkIsReviewed(chunk({ reviewed: false }))).toBe(false)
    expect(chunkIsReviewed(chunk({ reviewed: true }))).toBe(true)
  })

  it('reads a known parent with identity zero while rejecting non-containing ranges', () => {
    const parent = { ...chunk({ chunk_role: 'parent', parent_id: 0 }), index: 10, end_index: 10 }
    const child = { ...chunk({ chunk_role: 'child', parent_id: 0 }), start_index: 2, end_index: 5 }
    expect(getChunkParentRange(child, [parent, child])).toEqual({ start: 0, end: 10 })
    expect(getChunkParentRange(child, [{ ...parent, end_index: 3 }, child])).toBeNull()
  })

  it('keeps the actual JSON/draft boundaries and explicit empty edits', () => {
    expect(isJsonObject({ count: 0, active: false })).toBe(true)
    expect(isJsonObject(null)).toBe(false)
    expect(isJsonObject([])).toBe(false)
    expect(isChunkOverrideEdited({ content: '' })).toBe(true)
    expect(isChunkOverrideEdited({ metadata: {} })).toBe(true)
    expect(isChunkOverrideEdited(undefined)).toBe(false)
    expect(isChunkOverrideDisabled({ disabled: false })).toBe(false)
  })
})
