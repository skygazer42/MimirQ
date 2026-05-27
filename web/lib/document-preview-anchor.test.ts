import { describe, expect, it } from 'vitest'

import { buildPdfPreviewSrc, getDocumentPreviewAnchorFromCitation } from './document-preview-anchor'

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

  it('builds a PDF viewer fragment with toolbar, page, and search text', () => {
    expect(
      buildPdfPreviewSrc('https://example.com/doc.pdf#stale=1', {
        pageNumber: 12,
        searchText: 'policy clause',
      })
    ).toBe('https://example.com/doc.pdf#toolbar=0&page=12&search=policy+clause')
  })
})
