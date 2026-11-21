import { describe, expect, it } from 'vitest'

import { selectPdfPagesToReleaseForPool, selectPdfPagesToRender } from './pdf-render-canvas-pool'

describe('actual page canvas retention', () => {
  it('keeps every required visible page when a narrow page layout shows more than the cache target', () => {
    const visible = new Set(Array.from({ length: 8 }, (_, index) => index))

    const released = selectPdfPagesToReleaseForPool({
      renderedPages: visible,
      keepPage: 0,
      retainedPages: visible,
    })

    expect(released).toEqual([])
    expect([...visible]).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
  })

  it('releases distant unused pages while preserving required, queued and rendering resources', () => {
    const released = selectPdfPagesToReleaseForPool({
      renderedPages: new Set([0, 1, 2, 3, 4, 5, 6, 7]),
      keepPage: 4,
      retainedPages: new Set([3, 4, 5, 6]),
    })

    expect(released).toEqual([0, 7])
  })
})

describe('visible and nearby PDF page window', () => {
  it('keeps all actual visible pages while bounding only offscreen pre-render work', () => {
    const pages = Array.from({ length: 20 }, (_, index) => ({ index, top: index * 100, bottom: (index + 1) * 100 }))

    const window = selectPdfPagesToRender({ pages, viewportTop: 0, viewportBottom: 800, currentPageIndex: 0 })

    expect(window.currentPageIndex).toBe(0)
    expect(window.pageIndices).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
  })

  it('prioritizes visible pages and then the nearest real neighbors without mutating layout input', () => {
    const pages = Array.from({ length: 12 }, (_, index) => ({ index, top: index * 100, bottom: (index + 1) * 100 }))
    Object.freeze(pages)

    const window = selectPdfPagesToRender({ pages, viewportTop: 400, viewportBottom: 600, currentPageIndex: 4 })

    expect(window.currentPageIndex).toBe(4)
    expect(window.pageIndices).toEqual([4, 5, 3, 6, 2, 7])
    expect(pages[0].index).toBe(0)
  })
})

describe('current reading page in a vertical document', () => {
  it('preserves an explicitly requested completely visible short page', () => {
    const pages = Array.from({ length: 10 }, (_, index) => ({
      index,
      top: 28 + index * 174,
      bottom: 178 + index * 174,
    }))

    const window = selectPdfPagesToRender({ pages, viewportTop: 0, viewportBottom: 600, currentPageIndex: 1 })

    expect(window.currentPageIndex).toBe(1)
  })

  it('uses the largest visible fraction when the current page is no longer completely visible', () => {
    const window = selectPdfPagesToRender({
      pages: [
        { index: 0, top: -90, bottom: 10 },
        { index: 1, top: 34, bottom: 134 },
      ],
      viewportTop: 0,
      viewportBottom: 100,
      currentPageIndex: 0,
    })

    expect(window.currentPageIndex).toBe(1)
    expect(window.pageIndices).toEqual([1, 0])
  })
})
