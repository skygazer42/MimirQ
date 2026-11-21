import { beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/lib/api/core', () => ({ apiClient: client }))

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { auditApi } from './audit'

describe('audit response contracts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('exports the requested log scope as a blob and supports cancellation', async () => {
    const blob = new Blob(['row'])
    const signal = new AbortController().signal
    const params = { request_id: 'req-1', limit: 50, include_sensitive: false, gzip: true }
    client.get.mockResolvedValueOnce({ data: blob })

    await expect(auditApi.exportLogs(params, { signal })).resolves.toBe(blob)
    expect(client.get).toHaveBeenCalledExactlyOnceWith('/audit/logs/export', { params, signal, responseType: 'blob' })
  })

  it('returns the bounded deletion receipt including requested ids that were already missing', async () => {
    const ids = Array.from({ length: 500 }, (_, index) => `log-${index}`)
    const receipt = {
      requested: 500,
      deleted: 499,
      missing: 1,
      ids,
    }
    client.post.mockResolvedValueOnce({ data: receipt })

    await expect(auditApi.bulkDeleteLogs(ids)).resolves.toEqual(receipt)
    expect(client.post).toHaveBeenCalledExactlyOnceWith(
      '/audit/logs/bulk-delete',
      { ids },
      { timeout: API_LONG_TIMEOUT_MS },
    )
  })

  it('rejects an incomplete deletion response instead of discarding the missing ids', async () => {
    client.post.mockResolvedValueOnce({ data: { requested: 1, deleted: 1, missing: 0 } })

    await expect(auditApi.bulkDeleteLogs(['log-1'])).rejects.toThrow('invalid AuditLogDelete response')
  })

  it('rejects counters that do not account for every requested log', async () => {
    client.post.mockResolvedValueOnce({ data: { requested: 2, deleted: 1, missing: 0, ids: ['log-1', 'log-2'] } })

    await expect(auditApi.bulkDeleteLogs(['log-1', 'log-2'])).rejects.toThrow('Invalid audit log deletion receipt')
  })
})
