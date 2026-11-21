const MAX_RETAINED_PAGE_CANVASES = 6

const PAGE_PRERENDER_MARGIN_PX = 800

type PdfPageRange = Readonly<{ index: number; top: number; bottom: number }>

type PdfPageWindowOptions = {
  pages: readonly PdfPageRange[]
  viewportTop: number
  viewportBottom: number
  currentPageIndex: number
}

export function selectPdfPagesToRender({ pages, viewportTop, viewportBottom, currentPageIndex }: PdfPageWindowOptions) {
  const visible = pages
    .filter((page) => page.bottom > viewportTop && page.top < viewportBottom)
    .sort((left, right) => {
      const leftFraction =
        (Math.min(left.bottom, viewportBottom) - Math.max(left.top, viewportTop)) / (left.bottom - left.top)
      const rightFraction =
        (Math.min(right.bottom, viewportBottom) - Math.max(right.top, viewportTop)) / (right.bottom - right.top)
      return rightFraction - leftFraction || left.index - right.index
    })
  const current = visible.find((page) => page.index === currentPageIndex)
  const keepCurrent = current !== undefined && current.top >= viewportTop && current.bottom <= viewportBottom
  const visibleIds = new Set(visible.map((page) => page.index))
  const nearby = pages
    .filter(
      (page) =>
        !visibleIds.has(page.index) &&
        page.bottom > viewportTop - PAGE_PRERENDER_MARGIN_PX &&
        page.top < viewportBottom + PAGE_PRERENDER_MARGIN_PX,
    )
    .sort((left, right) => {
      const leftDistance = Math.max(viewportTop - left.bottom, left.top - viewportBottom, 0)
      const rightDistance = Math.max(viewportTop - right.bottom, right.top - viewportBottom, 0)
      return leftDistance - rightDistance || left.index - right.index
    })
  const remaining = Math.max(0, MAX_RETAINED_PAGE_CANVASES - visible.length)
  return {
    currentPageIndex: keepCurrent ? currentPageIndex : (visible[0]?.index ?? null),
    pageIndices: [...visible.map((page) => page.index), ...nearby.slice(0, remaining).map((page) => page.index)],
  }
}

type PdfPagePoolOptions = {
  renderedPages: ReadonlySet<number>
  keepPage: number
  retainedPages: ReadonlySet<number>
}

export function selectPdfPagesToReleaseForPool({
  renderedPages,
  keepPage,
  retainedPages,
}: PdfPagePoolOptions): number[] {
  const capacity = Math.max(MAX_RETAINED_PAGE_CANVASES, retainedPages.size)
  const overflow = renderedPages.size - capacity
  if (overflow <= 0) return []
  return [...renderedPages]
    .filter((pageIndex) => pageIndex !== keepPage && !retainedPages.has(pageIndex))
    .sort((left, right) => Math.abs(right - keepPage) - Math.abs(left - keepPage) || right - left)
    .slice(0, overflow)
}
