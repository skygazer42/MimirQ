import { describe, expect, it, vi } from 'vitest'

import { listDocumentPages } from './document-pages'

describe('complete document page reads', () => {
  it('preserves page order and forwards the exact next offset', async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'a' }, { id: 'b' }] })
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'c' }] })

    await expect(listDocumentPages(read, new AbortController().signal)).resolves.toEqual([
      { id: 'a' },
      { id: 'b' },
      { id: 'c' },
    ])
    expect(read.mock.calls).toEqual([[0], [2]])
  })

  it('rejects an early empty page instead of claiming a complete collection', async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ total: 50, items: [{ id: 'a' }] })
      .mockResolvedValueOnce({ total: 50, items: [] })

    await expect(listDocumentPages(read, new AbortController().signal)).rejects.toThrow('文档目录在读取时发生变化')
    expect(read).toHaveBeenCalledTimes(2)
  })

  it('rejects cancellation after a page completes before consuming it', async () => {
    const controller = new AbortController()
    const read = vi.fn(async () => {
      controller.abort()
      return { total: 2, items: [{ id: 'a' }] }
    })

    await expect(listDocumentPages(read, controller.signal)).rejects.toHaveProperty('name', 'AbortError')
    expect(read).toHaveBeenCalledOnce()
  })

  it('propagates a later page failure instead of returning a partial collection', async () => {
    const failure = new Error('next page unavailable')
    const read = vi
      .fn()
      .mockResolvedValueOnce({ total: 2, items: [{ id: 'a' }] })
      .mockRejectedValueOnce(failure)

    await expect(listDocumentPages(read, new AbortController().signal)).rejects.toBe(failure)
  })
  it('rejects total changes between offset pages', async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'a' }, { id: 'b' }] })
      .mockResolvedValueOnce({ total: 2, items: [] })
    await expect(listDocumentPages(read, new AbortController().signal)).rejects.toThrow('文档目录在读取时发生变化')
  })

  it('rejects a repeated identity instead of counting it toward completeness', async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'a' }, { id: 'b' }] })
      .mockResolvedValueOnce({ total: 3, items: [{ id: 'b' }] })
    await expect(listDocumentPages(read, new AbortController().signal)).rejects.toThrow('文档目录在读取时发生变化')
  })
})
