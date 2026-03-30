export const MAX_RETAINED_PAGE_CANVASES = 6

interface SelectPdfPagesToReleaseForPoolOptions {
  renderedPages: Iterable<number>
  keepPage: number
  maxRetainedPages?: number
  retainedPages?: ReadonlySet<number>
  queuedPages?: ReadonlySet<number>
  renderingPages?: ReadonlySet<number>
}

function toSortedUniquePageList(pages: Iterable<number>): number[] {
  const seen = new Set<number>()
  const result: number[] = []

  for (const pageIndex of pages) {
    if (!Number.isFinite(pageIndex) || pageIndex < 0 || seen.has(pageIndex)) continue
    seen.add(pageIndex)
    result.push(pageIndex)
  }

  result.sort((left, right) => left - right)
  return result
}

export function selectPdfPagesToReleaseForPool({
  renderedPages,
  keepPage,
  maxRetainedPages = MAX_RETAINED_PAGE_CANVASES,
  retainedPages = new Set<number>(),
  queuedPages = new Set<number>(),
  renderingPages = new Set<number>(),
}: SelectPdfPagesToReleaseForPoolOptions): number[] {
  const normalizedRenderedPages = toSortedUniquePageList(renderedPages)
  const normalizedKeepPage = Number.isFinite(keepPage) && keepPage >= 0 ? Math.trunc(keepPage) : 0
  const normalizedMaxRetainedPages = Math.max(1, Math.trunc(maxRetainedPages))

  if (normalizedRenderedPages.length <= normalizedMaxRetainedPages) {
    return []
  }

  const overflow = normalizedRenderedPages.length - normalizedMaxRetainedPages
  const releaseCandidates = normalizedRenderedPages.filter((pageIndex) => {
    if (pageIndex === normalizedKeepPage) return false
    if (queuedPages.has(pageIndex)) return false
    if (renderingPages.has(pageIndex)) return false
    return true
  })

  releaseCandidates.sort((left, right) => {
    const retainedDelta = Number(retainedPages.has(left)) - Number(retainedPages.has(right))
    if (retainedDelta !== 0) return retainedDelta

    const distanceDelta = Math.abs(right - normalizedKeepPage) - Math.abs(left - normalizedKeepPage)
    if (distanceDelta !== 0) return distanceDelta

    return right - left
  })

  return releaseCandidates.slice(0, overflow)
}
