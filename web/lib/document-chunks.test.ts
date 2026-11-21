import { describe, expect, it } from 'vitest'
import type { DocumentChunk } from '@/types/backend'

import { mapDocumentChunksToPreviewItems } from './document-chunks'

function chunk(patch: Partial<DocumentChunk> = {}): DocumentChunk {
  return {
    id: 'chunk-a',
    chunk_index: 0,
    content: '  text\n\n',
    start_char: null,
    end_char: null,
    page_number: null,
    disabled_at: null,
    created_at: null,
    updated_at: null,
    metadata: undefined,
    ...patch,
  }
}

describe('document text chunk positions', () => {
  it('preserves actual zero positions, empty text and absent metadata', () => {
    const items = mapDocumentChunksToPreviewItems(
      [chunk({ content: '', start_char: 0, end_char: 0, page_number: 0 })],
      '',
    )
    expect(items).toMatchObject([{ index: 0, content: '', length: 0, start_index: 0, end_index: 0, page_number: 0 }])
    expect(items[0].metadata).toBeUndefined()
    expect(items[0].tokens_est).toBeUndefined()
  })

  it.each([
    { start_char: null, end_char: null },
    { start_char: 4, end_char: null },
    { start_char: null, end_char: 8 },
    { start_char: 4, end_char: 2 },
    { start_char: -1, end_char: 2 },
  ])('omits unavailable or invalid text positions instead of inventing a span: %j', (positions) => {
    expect(mapDocumentChunksToPreviewItems([chunk(positions)], 'x'.repeat(30))).toEqual([])
  })

  it.each(['12px', '2.5', ''])('does not truncate or replace an invalid metadata offset: %s', (value) => {
    expect(
      mapDocumentChunksToPreviewItems([chunk({ metadata: { start_index: value, end_index: 20 } })], 'x'.repeat(30)),
    ).toEqual([])
  })

  it('retains the documented metadata offset inputs and gives actual column zero precedence', () => {
    const items = mapDocumentChunksToPreviewItems(
      [
        chunk({ id: 'metadata', chunk_index: 1, metadata: { start_index: '8', end_index: '12', flag: false } }),
        chunk({ id: 'column', start_char: 0, end_char: 4, metadata: { start_char: 9, end_char: 10 } }),
      ],
      'x'.repeat(30),
    )
    expect(items.map((item) => [item.index, item.start_index, item.end_index])).toEqual([
      [0, 0, 4],
      [1, 8, 12],
    ])
    expect(items[1].metadata).toEqual({ start_index: '8', end_index: '12', flag: false })
  })

  it('sorts the position projection without mutating server rows or their source content', () => {
    const content = '  text\n\n'
    const rows = [
      chunk({ id: 'later', chunk_index: 2, start_char: 10, end_char: 18 }),
      chunk({ id: 'earlier', chunk_index: 0, content, start_char: 0, end_char: 8 }),
    ]
    const items = mapDocumentChunksToPreviewItems(rows, 'x'.repeat(30))
    expect(rows.map((item) => item.id)).toEqual(['later', 'earlier'])
    expect(items.map((item) => item.index)).toEqual([0, 2])
    expect(items[0].content).toBe(content)
    expect(rows[1].content).toBe(content)
  })

  it('maps API code point spans and parent spans to the actual UTF-16 text view', () => {
    const text = '😀AB'
    const metadata = { chunk_role: 'child', parent_start_char: 0, parent_end_char: 3 }
    const items = mapDocumentChunksToPreviewItems(
      [chunk({ content: 'AB', start_char: 1, end_char: 3, metadata })],
      text,
    )
    expect([items[0].start_index, items[0].end_index]).toEqual([2, 4])
    expect(text.slice(items[0].start_index, items[0].end_index)).toBe('AB')
    expect(items[0].metadata).toMatchObject({ parent_start_char: 0, parent_end_char: 4 })
    expect(metadata).toEqual({ chunk_role: 'child', parent_start_char: 0, parent_end_char: 3 })
  })

  it('does not clamp spans outside the actual loaded source text', () => {
    expect(mapDocumentChunksToPreviewItems([chunk({ start_char: 1, end_char: 4 })], '😀AB')).toEqual([])
  })

  it('removes unusable parent offsets from the display projection instead of keeping their old units', () => {
    const items = mapDocumentChunksToPreviewItems(
      [chunk({ start_char: 1, end_char: 3, metadata: { parent_start_char: null, parent_end_char: 3, flag: false } })],
      '😀AB',
    )
    expect(items[0].metadata).toEqual({ flag: false })
  })
})
