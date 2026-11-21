import { describe, expect, it } from 'vitest'

import {
  getDocumentPreviewAnchorFromCitation,
  recoverDocumentPreviewAnchorFromChunkPositions,
  sanitizeDocumentPreviewAnchor,
} from './document-preview-anchor'

describe('citation position tag coordinates', () => {
  const tagged = 'first@@1 0 10 0 10##\n\nsecond@@2 20 30 20 30##'

  it('uses a known page instead of replacing it with the first tagged page', () => {
    const anchor = recoverDocumentPreviewAnchorFromChunkPositions({ pageNumber: 2 }, { content: tagged })
    expect(anchor).toMatchObject({ pageNumber: 2, bboxPageNumber: 2, bbox: { x0: 20, x1: 30, y0: 20, y1: 30 } })
  })

  it('retains a known unmatched page without inventing a different box', () => {
    expect(recoverDocumentPreviewAnchorFromChunkPositions({ pageNumber: 9 }, { content: tagged })).toEqual({
      pageNumber: 9,
    })
  })

  it('does not choose an arbitrary box when multiple positions have no target', () => {
    expect(recoverDocumentPreviewAnchorFromChunkPositions(null, { content: tagged })).toBeNull()
  })

  it('keeps a failed search as a search anchor instead of choosing the nearest unrelated box', () => {
    expect(
      recoverDocumentPreviewAnchorFromChunkPositions(
        { searchText: 'absent' },
        { content: tagged, start_char: 0 },
        { start: 1000, end: 1005 },
      ),
    ).toEqual({ searchText: 'absent' })
  })

  it('can use a unique position without a text target', () => {
    expect(recoverDocumentPreviewAnchorFromChunkPositions(null, { content: 'only@@3 1 2 3 4##' })).toMatchObject({
      pageNumber: 3,
      bboxPageNumber: 3,
    })
  })

  it('uses an explicitly known page from a multi-page position tag', () => {
    expect(
      recoverDocumentPreviewAnchorFromChunkPositions({ pageNumber: 2 }, { content: 'both@@1-2 1 2 3 4##' }),
    ).toMatchObject({ pageNumber: 2, bboxPageNumber: 2 })
  })

  it('uses an exact range when the same search text appears on different pages', () => {
    const text = 'same@@1 0 10 0 10##\n\nsame@@2 20 30 20 30##'
    const start = text.lastIndexOf('same')
    expect(
      recoverDocumentPreviewAnchorFromChunkPositions(
        { searchText: 'same' },
        { content: text, start_char: 100 },
        { start: 100 + start, end: 104 + start },
      ),
    ).toMatchObject({ pageNumber: 2, bboxPageNumber: 2, bbox: { x0: 20, x1: 30, y0: 20, y1: 30 } })
  })

  it('finds the matching occurrence on a known page', () => {
    const text = 'same@@1 0 10 0 10##\n\nsame@@2 20 30 20 30##'
    expect(
      recoverDocumentPreviewAnchorFromChunkPositions({ searchText: 'same', pageNumber: 2 }, { content: text }),
    ).toMatchObject({ pageNumber: 2, bboxPageNumber: 2, bbox: { x0: 20, x1: 30, y0: 20, y1: 30 } })
  })

  it('retains an ambiguous search without choosing its first occurrence', () => {
    const text = 'same@@1 0 10 0 10##\n\nsame@@2 20 30 20 30##'
    expect(recoverDocumentPreviewAnchorFromChunkPositions({ searchText: 'same' }, { content: text })).toEqual({
      searchText: 'same',
    })
  })

  it('does not apply chunk offsets to a different metadata text', () => {
    expect(
      recoverDocumentPreviewAnchorFromChunkPositions(
        null,
        { content: 'same', start_char: 100, metadata: { raw_content: tagged } },
        { start: 100, end: 104 },
      ),
    ).toBeNull()
  })

  it('keeps raw source indices when lowercase expands a character', () => {
    const text = `${'İ'.repeat(80)}first@@1 0 10 0 10##\n\nTARGET@@2 20 30 20 30##`
    expect(recoverDocumentPreviewAnchorFromChunkPositions({ searchText: 'target' }, { content: text })).toMatchObject({
      pageNumber: 2,
    })
  })

  it('matches case for supplementary letters without splitting their raw bounds', () => {
    const text = 'first@@1 0 10 0 10##\n\n𐐀@@2 20 30 20 30##'
    expect(recoverDocumentPreviewAnchorFromChunkPositions({ searchText: '𐐨' }, { content: text })).toMatchObject({
      pageNumber: 2,
    })
  })

  it('rejects fractional PDF pages and preserves valid bbox zero coordinates', () => {
    expect(sanitizeDocumentPreviewAnchor({ pageNumber: 2.9, searchText: 'target' })).toEqual({ searchText: 'target' })
    expect(sanitizeDocumentPreviewAnchor({ pageNumber: 0 })).toBeNull()
    expect(sanitizeDocumentPreviewAnchor({ pageNumber: 1, bbox: { x0: 0, y0: 0, x1: 10, y1: 20 } })).toMatchObject({
      bbox: { x0: 0, y0: 0, x1: 10, y1: 20 },
    })
  })

  it('limits search by whole characters rather than half a surrogate pair', () => {
    const anchor = getDocumentPreviewAnchorFromCitation({ chunk_content: `${'a'.repeat(119)}😀tail` })
    expect(Array.from(anchor!.searchText!)).toHaveLength(120)
    expect(anchor?.searchText?.endsWith('😀')).toBe(true)
  })
  it('uses backend code point spans to choose the actual tagged page after supplementary characters', () => {
    const text = `${'😀'.repeat(80)}left@@1 1 2 3 4##\n\nright@@2 10 20 30 40##`
    const start = Array.from(text.slice(0, text.indexOf('right'))).length
    const anchor = recoverDocumentPreviewAnchorFromChunkPositions(
      null,
      { content: text, start_char: 100 },
      { start: 100 + start, end: 100 + start + 5 },
    )
    expect(anchor).toMatchObject({ pageNumber: 2, bboxPageNumber: 2, bbox: { x0: 10, x1: 20, y0: 30, y1: 40 } })
  })

  it('retains a provided anchor box independently of an unavailable chunk position', () => {
    const anchor = { pageNumber: 2, bboxPageNumber: 2, bbox: { x0: 10, x1: 20, y0: 30, y1: 40 } }
    expect(recoverDocumentPreviewAnchorFromChunkPositions(anchor, null, null)).toEqual(anchor)
  })
})
