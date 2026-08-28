import { describe, expect, it } from 'vitest'

import {
  COST_ATTRIBUTION_PAGE_SIZE,
  paginateUsageRows,
} from './usage-pagination'

describe('usage cost attribution pagination', () => {
  it('uses ten rows per page and keeps an empty result on page one', () => {
    expect(COST_ATTRIBUTION_PAGE_SIZE).toBe(10)
    expect(paginateUsageRows([], 4)).toEqual({
      items: [],
      page: 1,
      pageCount: 1,
    })
  })

  it('returns the requested page from the complete sorted result', () => {
    const rows = Array.from({ length: 23 }, (_, index) => index + 1)

    expect(paginateUsageRows(rows, 2)).toEqual({
      items: [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
      page: 2,
      pageCount: 3,
    })
  })

  it('clamps stale page state after the result set becomes shorter', () => {
    expect(paginateUsageRows([1, 2, 3], 8)).toEqual({
      items: [1, 2, 3],
      page: 1,
      pageCount: 1,
    })
  })
})
