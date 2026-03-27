import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ROOT_FOLDER_ID, useParsedFiles } from './use-parsed-files-store'

const cacheMocks = vi.hoisted(() => ({
  saveDocContentToCache: vi.fn(),
  deleteDocContentFromCache: vi.fn(),
  deleteDocSourceFromCache: vi.fn(),
}))

vi.mock('@/lib/doc-content-cache', () => ({
  saveDocContentToCache: cacheMocks.saveDocContentToCache,
  deleteDocContentFromCache: cacheMocks.deleteDocContentFromCache,
  deleteDocSourceFromCache: cacheMocks.deleteDocSourceFromCache,
}))

function createDeferred<T>() {
  let resolve: (value: T | PromiseLike<T>) => void = () => {}
  let reject: (reason?: unknown) => void = () => {}
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useParsedFiles updateParsedFile persistence reliability', () => {
  beforeEach(() => {
    cacheMocks.saveDocContentToCache.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    useParsedFiles.setState({
      files: [],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
      isLoaded: false,
    })
    ;(globalThis as { window?: unknown }).window = {}
  })

  it('waits for markdown cache persistence before setting parsed status', async () => {
    const fileId = useParsedFiles.getState().addParsedFile({
      filename: 'sample.md',
      fileType: 'md',
      fileSize: 10,
      markdownContent: 'old',
      parser: 'Auto',
      status: 'parsing',
    })
    const deferred = createDeferred<void>()
    cacheMocks.saveDocContentToCache.mockImplementation(() => deferred.promise)

    const updatePromise = useParsedFiles.getState().updateParsedFile(fileId, {
      markdownContent: '# persisted',
      originalMarkdownContent: '# persisted',
      status: 'parsed',
    })

    expect(cacheMocks.saveDocContentToCache).toHaveBeenCalledTimes(1)
    expect(useParsedFiles.getState().getFile(fileId)?.status).toBe('parsing')

    deferred.resolve()
    await updatePromise

    const updated = useParsedFiles.getState().getFile(fileId)
    expect(updated?.status).toBe('parsed')
    expect(updated?.markdownContent).toBe('# persisted')
    expect(updated?.originalMarkdownContent).toBe('# persisted')
  })

  it('retries parsed markdown persistence before applying parsed status', async () => {
    const fileId = useParsedFiles.getState().addParsedFile({
      filename: 'sample.md',
      fileType: 'md',
      fileSize: 10,
      markdownContent: 'old',
      parser: 'Auto',
      status: 'parsing',
    })
    cacheMocks.saveDocContentToCache
      .mockRejectedValueOnce(new Error('temporary transaction abort'))
      .mockResolvedValueOnce(undefined)

    await expect(
      useParsedFiles.getState().updateParsedFile(fileId, {
        markdownContent: '# retried',
        originalMarkdownContent: '# retried',
        status: 'parsed',
      })
    ).resolves.toBeUndefined()

    expect(cacheMocks.saveDocContentToCache).toHaveBeenCalledTimes(2)
    expect(useParsedFiles.getState().getFile(fileId)?.status).toBe('parsed')
  })

  it('does not let an older parsed write clobber a newer library update', async () => {
    const fileId = useParsedFiles.getState().addParsedFile({
      filename: 'sample.md',
      fileType: 'md',
      fileSize: 10,
      markdownContent: 'old',
      parser: 'Auto',
      status: 'parsing',
    })
    const deferred = createDeferred<void>()
    cacheMocks.saveDocContentToCache.mockImplementationOnce(() => deferred.promise)

    const staleParsedWrite = useParsedFiles.getState().updateParsedFile(fileId, {
      markdownContent: '# stale result',
      originalMarkdownContent: '# stale result',
      parser: 'Old parser',
      status: 'parsed',
    })

    await useParsedFiles.getState().updateParsedFile(fileId, {
      status: 'parsing',
      parser: 'New parser',
      error: undefined,
    })

    deferred.resolve()
    await staleParsedWrite

    const updated = useParsedFiles.getState().getFile(fileId)
    expect(updated?.status).toBe('parsing')
    expect(updated?.parser).toBe('New parser')
    expect(updated?.markdownContent).toBe('old')
  })

  it('falls back to parsed status when cache persistence fails', async () => {
    const fileId = useParsedFiles.getState().addParsedFile({
      filename: 'sample.md',
      fileType: 'md',
      fileSize: 10,
      markdownContent: 'old',
      parser: 'Auto',
      status: 'parsing',
    })
    cacheMocks.saveDocContentToCache
      .mockRejectedValueOnce(new Error('IndexedDB unavailable in private mode'))
      .mockRejectedValueOnce(new Error('IndexedDB unavailable in private mode'))
      .mockRejectedValueOnce(new Error('IndexedDB unavailable in private mode'))

    await expect(
      useParsedFiles.getState().updateParsedFile(fileId, {
        markdownContent: 'fallback markdown',
        originalMarkdownContent: 'fallback markdown',
        status: 'parsed',
      })
    ).resolves.toBeUndefined()

    const updated = useParsedFiles.getState().getFile(fileId)
    expect(updated?.status).toBe('parsed')
    expect(updated?.markdownContent).toBe('fallback markdown')
    expect(updated?.originalMarkdownContent).toBe('fallback markdown')
    expect(console.warn).toHaveBeenCalledTimes(1)
  })
})
