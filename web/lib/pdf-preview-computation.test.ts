import { describe, expect, it } from 'vitest'

import { computePdfPreviewData } from './pdf-preview-computation'

describe('PDF overlay coordinate and identity projection', () => {
  it('maps code-point chunk offsets after a surrogate pair to the actual positioned block', () => {
    const rawOriginal = '😀A@@1 0 10 0 10##B@@2 0 10 0 10##'
    const start = Array.from(rawOriginal.slice(0, rawOriginal.indexOf('B'))).length
    const chunks = [{ start_index: start, end_index: start + 1 }]
    Object.freeze(chunks[0])
    Object.freeze(chunks)

    const result = computePdfPreviewData({ rawOriginal, previewChunks: chunks })

    expect(new Map(result.chunkBlockIdsByIndexEntries).get(0)).toEqual(['block-1'])
    expect(new Map(result.blockIdToChunkIndexEntries).get('block-1')).toBe(0)
    expect(new Map(result.blockIdToChunkIndexEntries).has('block-0')).toBe(false)
    expect(new Map(result.blockIdToPageIndexEntries).get('block-1')).toBe(1)
    expect(chunks).toEqual([{ start_index: start, end_index: start + 1 }])
  })

  it('omits an invalid chunk range without turning it into the first block or shifting later source positions', () => {
    const rawOriginal = 'AB@@1 0 10 0 10##CD@@2 0 10 0 10##'
    const start = rawOriginal.indexOf('CD')
    const result = computePdfPreviewData({
      rawOriginal,
      previewChunks: [
        { start_index: Number.NaN, end_index: 2 },
        { start_index: start, end_index: start + 2 },
      ],
    })

    expect(new Map(result.blockIdToChunkIndexEntries).has('block-0')).toBe(false)
    expect(new Map(result.blockIdToChunkIndexEntries).get('block-1')).toBe(1)
    expect(new Map(result.chunkBlockIdsByIndexEntries).get(1)).toEqual(['block-1'])
  })

  it('preserves every explicit page in a position tag, including the real first page', () => {
    const result = computePdfPreviewData({
      rawOriginal: 'text@@1-2 0 10 0 10##',
      previewChunks: [{ start_index: 0, end_index: 4 }],
    })

    expect([...new Map(result.boxesByPageEntries).keys()]).toEqual([0, 1])
    expect(new Map(result.blockIdToPageIndexEntries).get('block-0')).toBe(0)
  })

  it('does not invent the first page for a tag without a valid page number', () => {
    const result = computePdfPreviewData({
      rawOriginal: 'text@@0 0 10 0 10##',
      previewChunks: [{ start_index: 0, end_index: 4 }],
    })

    expect(result.boxesByPageEntries).toEqual([])
    expect(result.blockIdToPageIndexEntries).toEqual([])
    expect(result.blockIdToChunkIndexEntries).toEqual([])
  })

  it('keeps every positioned block belonging to a selected large chunk', () => {
    const rawOriginal = Array.from({ length: 601 }, () => 'a@@1 0 10 0 10##').join('')
    const result = computePdfPreviewData({
      rawOriginal,
      previewChunks: [{ start_index: 0, end_index: Array.from(rawOriginal).length }],
    })
    const pageBoxes = new Map(result.boxesByPageEntries).get(0)!

    expect(new Map(result.chunkBlockIdsByIndexEntries).get(0)).toEqual(pageBoxes.map((box) => box.id))
    expect(new Map(result.blockIdToChunkIndexEntries).get(pageBoxes.at(-1)!.id)).toBe(0)
  })
})
