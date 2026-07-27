import { beforeEach, describe, expect, it, vi } from 'vitest'

const openapi = vi.hoisted(() => ({
  request: vi.fn(),
}))

vi.mock('@/lib/api/core', () => ({
  API_TIMEOUT_MS: 10_000,
  apiClient: {},
  openapiRequest: openapi.request,
}))

import { listAllDatasets } from './datasets'

describe('listAllDatasets', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reads every dataset page until the reported total is reached', async () => {
    openapi.request
      .mockResolvedValueOnce({
        total: 450,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${index}` })),
      })
      .mockResolvedValueOnce({
        total: 450,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${200 + index}` })),
      })
      .mockResolvedValueOnce({
        total: 450,
        items: Array.from({ length: 50 }, (_, index) => ({ id: `dataset-${400 + index}` })),
      })

    const datasets = await listAllDatasets()

    expect(datasets).toHaveLength(450)
    expect(openapi.request).toHaveBeenCalledTimes(3)
    expect(openapi.request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        path: '/api/v1/datasets/',
        method: 'get',
        query: { skip: 0, limit: 200 },
      })
    )
    expect(openapi.request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        query: { skip: 200, limit: 200 },
      })
    )
    expect(openapi.request).toHaveBeenNthCalledWith(
      3,
      expect.objectContaining({
        query: { skip: 400, limit: 200 },
      })
    )
  })

  it('preserves filters while paging exhaustive dataset reads', async () => {
    openapi.request
      .mockResolvedValueOnce({
        total: 205,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `filtered-${index}` })),
      })
      .mockResolvedValueOnce({
        total: 205,
        items: Array.from({ length: 5 }, (_, index) => ({ id: `filtered-${200 + index}` })),
      })

    await listAllDatasets({
      category_id: 'cat-1',
      include_descendants: true,
      q: 'finance',
    })

    expect(openapi.request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        query: {
          skip: 0,
          limit: 200,
          category_id: 'cat-1',
          include_descendants: true,
          q: 'finance',
        },
      })
    )
    expect(openapi.request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        query: {
          skip: 200,
          limit: 200,
          category_id: 'cat-1',
          include_descendants: true,
          q: 'finance',
        },
      })
    )
  })

  it('stops when a later full page repeats only already-seen dataset ids', async () => {
    openapi.request
      .mockResolvedValueOnce({
        total: 10_000,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${index}` })),
      })
      .mockResolvedValueOnce({
        total: 10_000,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${index}` })),
      })

    const datasets = await listAllDatasets()

    expect(datasets).toHaveLength(200)
    expect(openapi.request).toHaveBeenCalledTimes(2)
  })

  it('treats invalid totals as untrusted and still terminates on a short page', async () => {
    openapi.request
      .mockResolvedValueOnce({
        total: 'not-a-number',
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${index}` })),
      })
      .mockResolvedValueOnce({
        total: 'not-a-number',
        items: Array.from({ length: 5 }, (_, index) => ({ id: `dataset-${200 + index}` })),
      })

    const datasets = await listAllDatasets()

    expect(datasets).toHaveLength(205)
    expect(openapi.request).toHaveBeenCalledTimes(2)
  })
})
