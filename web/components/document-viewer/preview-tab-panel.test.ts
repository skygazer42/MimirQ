import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { PreviewTabPanel } from './preview-tab-panel'

describe('PreviewTabPanel', () => {
  it('uses the pdf.js viewer for citation page anchors and surfaces return actions', () => {
    const html = renderToStaticMarkup(
      React.createElement(PreviewTabPanel, {
        isLoading: false,
        doc: { id: 'doc-1', filename: 'Policy.pdf', file_type: 'pdf' } as any,
        canInlinePreview: true,
        fileUrl: 'https://example.com/doc.pdf',
        rawFileUrl: 'https://example.com/raw.pdf',
        downloadUrl: 'https://example.com/download.pdf',
        previewAnchor: { pageNumber: 4, searchText: 'retention period' },
        highlightChunkId: 'chunk-9',
        highlightRange: { start: 10, end: 24 },
        onViewText: () => {},
        onViewChunks: () => {},
      })
    )

    expect(html).toContain('data-pdfjs-document-preview="true"')
    expect(html).not.toContain('<iframe')
    expect(html).toContain('PDF 已跳转到引用页')
    expect(html).toContain('aria-label="收起引用定位"')
    expect(html).toContain('查看文本高亮')
    expect(html).toContain('查看切片')
  })

  it('uses the PDF bbox overlay viewer when a citation anchor includes coordinates', () => {
    const html = renderToStaticMarkup(
      React.createElement(PreviewTabPanel, {
        isLoading: false,
        doc: { id: 'doc-1', filename: 'Policy.pdf', file_type: 'pdf' } as any,
        canInlinePreview: true,
        fileUrl: 'https://example.com/doc.pdf',
        rawFileUrl: 'https://example.com/raw.pdf',
        downloadUrl: 'https://example.com/download.pdf',
        previewAnchor: {
          bbox: { x0: 10, y0: 20, x1: 160, y1: 90 },
          bboxPageNumber: 4,
          pageNumber: 4,
          searchText: 'retention period',
        },
        highlightChunkId: 'chunk-9',
        highlightRange: { start: 10, end: 24 },
        onViewText: () => {},
        onViewChunks: () => {},
      })
    )

    expect(html).toContain('data-citation-bbox-preview="true"')
    expect(html).not.toContain('<iframe')
  })
})
