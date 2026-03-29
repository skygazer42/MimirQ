import { describe, expect, it } from 'vitest'

import { shouldRevealPdfPreviewOnChunkSelect } from './pdf-dock'

describe('pdf dock helpers', () => {
  it('only reopens the original panel for hidden pdf selections under persisted pdf mode', () => {
    expect(
      shouldRevealPdfPreviewOnChunkSelect({
        nextIndex: 3,
        showOriginalPanel: false,
        isPdf: true,
        preferredPreviewMode: 'pdf',
      })
    ).toBe(true)

    expect(
      shouldRevealPdfPreviewOnChunkSelect({
        nextIndex: null,
        showOriginalPanel: false,
        isPdf: true,
        preferredPreviewMode: 'pdf',
      })
    ).toBe(false)

    expect(
      shouldRevealPdfPreviewOnChunkSelect({
        nextIndex: 3,
        showOriginalPanel: true,
        isPdf: true,
        preferredPreviewMode: 'pdf',
      })
    ).toBe(false)

    expect(
      shouldRevealPdfPreviewOnChunkSelect({
        nextIndex: 3,
        showOriginalPanel: false,
        isPdf: false,
        preferredPreviewMode: 'pdf',
      })
    ).toBe(false)

    expect(
      shouldRevealPdfPreviewOnChunkSelect({
        nextIndex: 3,
        showOriginalPanel: false,
        isPdf: true,
        preferredPreviewMode: 'raw',
      })
    ).toBe(false)
  })
})
