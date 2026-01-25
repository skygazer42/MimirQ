import { describe, expect, it } from 'vitest'
import type { DocumentChunk } from '@/types'
import { mapDocumentChunksToPreviewItems } from './document-chunks'

describe('mapDocumentChunksToPreviewItems', () => {
  it('uses start_char/end_char when provided', () => {
    const chunks: DocumentChunk[] = [
      { id: 'c1', chunk_index: 0, content: 'hello', start_char: 10, end_char: 20, page_number: 1, metadata: {} },
    ]
    const out = mapDocumentChunksToPreviewItems(chunks)
    expect(out[0].start_index).toBe(10)
    expect(out[0].end_index).toBe(20)
  })

  it('falls back to end=start+len when end is missing', () => {
    const chunks: DocumentChunk[] = [
      { id: 'c1', chunk_index: 0, content: 'hello', start_char: 10, page_number: 1, metadata: {} },
    ]
    const out = mapDocumentChunksToPreviewItems(chunks)
    expect(out[0].start_index).toBe(10)
    expect(out[0].end_index).toBe(15)
  })

  it('falls back to metadata offsets when DB fields are missing', () => {
    const chunks: DocumentChunk[] = [
      { id: 'c1', chunk_index: 0, content: 'hello', metadata: { start_char: 7, end_char: 9 } },
    ]
    const out = mapDocumentChunksToPreviewItems(chunks)
    expect(out[0].start_index).toBe(7)
    expect(out[0].end_index).toBe(9)
  })

  it('sorts by chunk_index', () => {
    const chunks: DocumentChunk[] = [
      { id: 'c2', chunk_index: 2, content: 'b', start_char: 0, end_char: 1, metadata: {} },
      { id: 'c1', chunk_index: 1, content: 'a', start_char: 1, end_char: 2, metadata: {} },
    ]
    const out = mapDocumentChunksToPreviewItems(chunks)
    expect(out.map((x) => x.index)).toEqual([1, 2])
  })
})

