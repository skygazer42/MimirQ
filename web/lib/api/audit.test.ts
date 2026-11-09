import { beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/lib/api/core', () => ({ apiClient: client }))

import { auditApi } from './audit'

describe('audit response contracts', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('preserves the export body and its continuation cursor', async () => {
    const blob = new Blob(['row'])
    const cursor = { after_kind: 'grant', after_created_at: '2026-10-26T00:00:00Z', after_id: 'grant-id' }
    client.get.mockResolvedValueOnce({ data: blob, headers: { 'x-next-cursor': JSON.stringify(cursor) } })

    await expect(auditApi.exportAccessGraphPage()).resolves.toEqual({ blob, nextCursor: cursor })
  })

  it('uses an absent continuation header to identify the final export page', async () => {
    const blob = new Blob(['row'])
    client.get.mockResolvedValueOnce({ data: blob, headers: {} })

    await expect(auditApi.exportAccessGraphPage()).resolves.toEqual({ blob, nextCursor: null })
  })

  it.each(['broken json', 'null', '{}'])('rejects malformed continuation data: %s', async (header) => {
    client.get.mockResolvedValueOnce({ data: new Blob(['row']), headers: { 'x-next-cursor': header } })

    await expect(auditApi.exportAccessGraphPage()).rejects.toBeInstanceOf(Error)
  })

  it('aggregates required counters and ids across bulk deletion chunks', async () => {
    const ids = Array.from({ length: 501 }, (_, index) => `log-${index}`)
    client.post
      .mockResolvedValueOnce({ data: { requested: 500, deleted: 499, missing: 1, ids: ids.slice(0, 499) } })
      .mockResolvedValueOnce({ data: { requested: 1, deleted: 1, missing: 0, ids: ids.slice(500) } })

    await expect(auditApi.bulkDeleteLogs(ids)).resolves.toEqual({
      requested: 501, deleted: 500, missing: 1, ids: [...ids.slice(0, 499), ids[500]],
    })
    expect(client.post).toHaveBeenCalledTimes(2)
  })

  it('rejects an incomplete deletion response instead of discarding the missing ids', async () => {
    client.post.mockResolvedValueOnce({ data: { requested: 1, deleted: 1, missing: 0 } })

    await expect(auditApi.bulkDeleteLogs(['log-1'])).rejects.toBeInstanceOf(TypeError)
  })
})
