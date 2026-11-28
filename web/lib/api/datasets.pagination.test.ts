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
    openapi.request.mockReset()
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
      }),
    )
    expect(openapi.request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        query: { skip: 200, limit: 200 },
      }),
    )
    expect(openapi.request).toHaveBeenNthCalledWith(
      3,
      expect.objectContaining({
        query: { skip: 400, limit: 200 },
      }),
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
      }),
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
      }),
    )
  })

  it('rejects an incomplete directory when a later page repeats already-seen ids', async () => {
    openapi.request
      .mockResolvedValueOnce({
        total: 400,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${index}` })),
      })
      .mockResolvedValueOnce({
        total: 400,
        items: Array.from({ length: 200 }, (_, index) => ({ id: `dataset-${index}` })),
      })

    await expect(listAllDatasets()).rejects.toThrow('数据集目录在读取期间发生变化，请重新读取')
    expect(openapi.request).toHaveBeenCalledTimes(2)
  })

  it('rejects an invalid total before requesting another page', async () => {
    openapi.request.mockResolvedValueOnce({
      total: 'not-a-number',
      items: [{ id: 'dataset-a' }],
    })

    await expect(listAllDatasets()).rejects.toThrow('数据集目录总数无效，请重新读取')
    expect(openapi.request).toHaveBeenCalledOnce()
  })

  it('does not convert a missing required items envelope into a successful empty list', async () => {
    openapi.request.mockResolvedValueOnce({ total: 2 })

    await expect(listAllDatasets()).rejects.toBeInstanceOf(TypeError)
    expect(openapi.request).toHaveBeenCalledOnce()
  })

  it('forwards the query cancellation signal through every dataset page', async () => {
    const signal = new AbortController().signal
    openapi.request
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'dataset-a' }, { id: 'dataset-b' }] })
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'dataset-c' }] })

    const datasets = await listAllDatasets({ pageSize: 2 }, { signal })

    expect(datasets).toHaveLength(3)
    expect(openapi.request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ query: { skip: 0, limit: 2 }, signal }),
    )
    expect(openapi.request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ query: { skip: 2, limit: 2 }, signal }),
    )
  })
})
