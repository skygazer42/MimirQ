export const COST_ATTRIBUTION_PAGE_SIZE = 10

export function paginateUsageRows<T>(
  rows: readonly T[],
  requestedPage: number,
  pageSize = COST_ATTRIBUTION_PAGE_SIZE
): { items: T[]; page: number; pageCount: number } {
  const safePageSize = Math.max(1, Math.trunc(pageSize))
  const pageCount = Math.max(1, Math.ceil(rows.length / safePageSize))
  const normalizedPage = Number.isFinite(requestedPage)
    ? Math.trunc(requestedPage)
    : 1
  const page = Math.min(pageCount, Math.max(1, normalizedPage))
  const start = (page - 1) * safePageSize

  return {
    items: rows.slice(start, start + safePageSize),
    page,
    pageCount,
  }
}
