import { describe, expect, it } from 'vitest'

import { computePdfPreviewData } from './pdf-preview-computation'

describe('pdf-preview-computation', () => {
  it('precomputes positioned blocks, cleaned chunk ranges, and block-to-chunk matches', () => {
    const rawOriginal = 'A@@1\t0.1\t0.2\t0.3\t0.4##B@@2\t0.2\t0.3\t0.4\t0.5##'
    const firstTagStart = rawOriginal.indexOf('@@1')
    const firstTagEnd = rawOriginal.indexOf('##') + 2
    const secondTagStart = rawOriginal.indexOf('@@2')
    const previewChunks = [
      { start_index: 0, end_index: firstTagStart },
      { start_index: firstTagEnd, end_index: secondTagStart },
    ]

    const result = computePdfPreviewData({ rawOriginal, previewChunks })

    expect(result.blocksWithPositions.map((block) => block.text)).toEqual(['A', 'B'])
    expect(result.blockRanges).toEqual([
      { id: 'block-0', start: 0, end: 1 },
      { id: 'block-1', start: 1, end: 2 },
    ])
    expect(result.chunkRanges).toEqual([
      { index: 0, start: 0, end: 1 },
      { index: 1, start: 1, end: 2 },
    ])
    expect(result.blockIdToChunkIndexEntries).toEqual([
      ['block-0', 0],
      ['block-1', 1],
    ])
  })
})
