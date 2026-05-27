import { describe, expect, it } from 'vitest'

import {
  buildDocumentPreviewBboxOverlay,
  buildPdfPreviewSrc,
  recoverDocumentPreviewAnchorFromChunkPositions,
  getDocumentPreviewAnchorFromCitation,
} from './document-preview-anchor'

describe('document preview anchor helpers', () => {
  it('prefers citation snippets over broad matched terms for source positioning', () => {
    expect(
      getDocumentPreviewAnchorFromCitation({
        chunk_content: 'fallback snippet',
        matched_terms: [' retention window ', 'backup'],
        page_number: 7,
      })
    ).toEqual({
      pageNumber: 7,
      searchText: 'fallback snippet',
    })
  })

  it('normalizes citation bbox anchors into a single active PDF overlay box', () => {
    const anchor = getDocumentPreviewAnchorFromCitation({
      bbox: { x0: 10, y0: 20, x1: 160, y1: 90 },
      chunk_content: 'quoted layout block',
      matched_terms: ['layout'],
      page_number: 4,
    })

    expect(anchor).toEqual({
      bbox: { x0: 10, y0: 20, x1: 160, y1: 90 },
      bboxPageNumber: 4,
      pageNumber: 4,
      searchText: 'quoted layout block',
    })

    const overlay = buildDocumentPreviewBboxOverlay(anchor)

    expect(overlay?.activeBlockIds).toEqual(['citation-bbox'])
    expect(overlay?.blockIdToPageIndex.get('citation-bbox')).toBe(3)
    expect(overlay?.boxesByPage.get(3)?.[0]).toMatchObject({
      id: 'citation-bbox',
      position: {
        bottom: 90,
        left: 10,
        pages: [3],
        raw: 'citation-bbox',
        right: 160,
        top: 20,
      },
    })
  })

  it('builds a PDF viewer fragment with toolbar, page, and search text', () => {
    expect(
      buildPdfPreviewSrc('https://example.com/doc.pdf#stale=1', {
        pageNumber: 12,
        searchText: 'policy clause',
      })
    ).toBe('https://example.com/doc.pdf#toolbar=0&page=12&search=policy+clause')
  })

  it('recovers a PDF bbox from deepdoc position tags for old history anchors', () => {
    const content =
      'Deeper neural networks are more difficult to train.@@1 90 260 120 150## ' +
      'We present a residual learning framework and shortcut connections for very deep networks.@@2 47 288 495 592##'
    const targetStart = content.indexOf('shortcut connections')
    const targetEnd = targetStart + 'shortcut connections'.length

    expect(
      recoverDocumentPreviewAnchorFromChunkPositions(
        { pageNumber: 1, searchText: 'shortcut connections' },
        {
          content,
          page_number: 1,
          start_char: 1000,
          metadata: {},
        },
        { start: 1000 + targetStart, end: 1000 + targetEnd }
      )
    ).toEqual({
      bbox: { x0: 47, y0: 495, x1: 288, y1: 592 },
      bboxPageNumber: 2,
      pageNumber: 2,
      searchText: 'shortcut connections',
    })
  })

  it('does not override citation bbox anchors that already include geometry', () => {
    expect(
      recoverDocumentPreviewAnchorFromChunkPositions(
        {
          bbox: { x0: 1, y0: 2, x1: 3, y1: 4 },
          bboxPageNumber: 5,
          pageNumber: 5,
          searchText: 'existing',
        },
        {
          content: 'other text@@1 10 20 30 40##',
          page_number: 1,
          metadata: {},
        },
        null
      )
    ).toEqual({
      bbox: { x0: 1, y0: 2, x1: 3, y1: 4 },
      bboxPageNumber: 5,
      pageNumber: 5,
      searchText: 'existing',
    })
  })
})
