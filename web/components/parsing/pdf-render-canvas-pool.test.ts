import { describe, expect, it } from 'vitest'

import {
  MAX_RETAINED_PAGE_CANVASES,
  selectPdfPagesToReleaseForPool,
} from '@/components/parsing/pdf-render-canvas-pool'

describe('pdf render canvas pool', () => {
  it('returns no pages when the rendered set is already within budget', () => {
    expect(
      selectPdfPagesToReleaseForPool({
        renderedPages: [0, 1, 2],
        keepPage: 1,
      })
    ).toEqual([])
  })

  it('prefers evicting non-retained pages before retained neighbors', () => {
    expect(
      selectPdfPagesToReleaseForPool({
        renderedPages: [2, 3, 4, 5],
        keepPage: 4,
        maxRetainedPages: 2,
        retainedPages: new Set([3, 4]),
      })
    ).toEqual([2, 5])
  })

  it('never evicts the current, queued, or actively rendering pages', () => {
    expect(
      selectPdfPagesToReleaseForPool({
        renderedPages: [0, 1, 2, 3, 4],
        keepPage: 2,
        maxRetainedPages: 2,
        queuedPages: new Set([4]),
        renderingPages: new Set([1]),
      })
    ).toEqual([0, 3])
  })

  it('falls back to evicting the farthest retained pages when every page is still retained', () => {
    expect(
      selectPdfPagesToReleaseForPool({
        renderedPages: [4, 5, 6, 7, 8],
        keepPage: 6,
        maxRetainedPages: 3,
        retainedPages: new Set([4, 5, 6, 7, 8]),
      })
    ).toEqual([8, 4])
  })

  it('ships with a conservative default budget for live rasterized pages', () => {
    expect(MAX_RETAINED_PAGE_CANVASES).toBeGreaterThanOrEqual(4)
    expect(MAX_RETAINED_PAGE_CANVASES).toBeLessThanOrEqual(8)
  })
})
