export const COST_ATTRIBUTION_PAGE_SIZE = 10

export function paginateUsageRows<T>(
  rows: readonly T[],
  requestedPage: number,
): { items: T[]; page: number; pageCount: number } {
  const pageCount = Math.max(1, Math.ceil(rows.length / COST_ATTRIBUTION_PAGE_SIZE))
  const page = Math.min(pageCount, requestedPage)
  const start = (page - 1) * COST_ATTRIBUTION_PAGE_SIZE

  return {
    items: rows.slice(start, start + COST_ATTRIBUTION_PAGE_SIZE),
    page,
    pageCount,
  }
}
