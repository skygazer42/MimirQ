// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

const authMock = vi.hoisted(() => ({
  scope: 'default:anonymous',
}))
const cacheMock = vi.hoisted(() => ({
  saveDocContentToCache: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAuthCacheScope: () => authMock.scope,
}))

vi.mock('@/lib/doc-content-cache', () => ({
  deleteDocContentFromCache: vi.fn(),
  deleteDocSourceFromCache: vi.fn(),
  saveDocContentToCache: cacheMock.saveDocContentToCache,
}))

vi.mock('@/lib/request-id', () => ({
  generateRequestId: vi.fn(() => 'generated-id'),
}))

import { ROOT_FOLDER_ID, useParsedFiles } from './use-parsed-files-store'
import { deleteDocContentFromCache, deleteDocSourceFromCache, saveDocContentToCache } from '@/lib/doc-content-cache'

function makePersistedState(filename: string, id = `${filename}-id`) {
  return JSON.stringify({
    state: {
      files: [
        {
          id,
          filename,
          fileType: 'md',
          fileSize: 1,
          markdownContent: '',
          originalMarkdownContent: '',
          parsedAt: '2026-07-25T00:00:00.000Z',
          parser: 'test',
          folderId: ROOT_FOLDER_ID,
          status: 'parsed',
        },
      ],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
    },
    version: 0,
  })
}

function resetParsedFilesStore() {
  useParsedFiles.setState({
    files: [],
    folders: [],
    activeFolderId: ROOT_FOLDER_ID,
    isLoaded: false,
  })
  useParsedFiles.persist.clearStorage()
}

describe('useParsedFiles auth scope persistence', () => {
  beforeEach(() => {
    cacheMock.saveDocContentToCache.mockReset().mockResolvedValue(undefined)
    localStorage.clear()
    sessionStorage.clear()
    authMock.scope = 'default:anonymous'
    resetParsedFilesStore()
  })

  it('persists parsed file metadata under the active auth scope key', () => {
    useParsedFiles.getState().addParsedFile({
      filename: 'same-scope.md',
      fileType: 'md',
      fileSize: 1,
      markdownContent: '# doc',
      parser: 'unit-test',
    })

    expect(localStorage.getItem('mimirq_parsed_files:default:anonymous')).toContain('same-scope.md')
    expect(localStorage.getItem('mimirq_parsed_files')).toBeNull()
  })

  it('resets and rehydrates from the new auth scope when the scope changes', async () => {
    localStorage.setItem(
      'mimirq_parsed_files:tenant-b:user-b',
      makePersistedState('tenant-b-file.md')
    )

    useParsedFiles.getState().addParsedFile({
      filename: 'tenant-a-file.md',
      fileType: 'md',
      fileSize: 1,
      markdownContent: '# doc',
      parser: 'unit-test',
    })

    authMock.scope = 'tenant-b:user-b'
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().files.map((file) => file.filename)).toEqual(['tenant-b-file.md'])
    expect(useParsedFiles.getState().activeFolderId).toBe(ROOT_FOLDER_ID)
  })

  it('does not apply a pending update from the previous auth scope', async () => {
    let finishOldWrite: (() => void) | undefined
    cacheMock.saveDocContentToCache.mockImplementationOnce(
      () => new Promise<void>((resolve) => {
        finishOldWrite = resolve
      })
    )
    useParsedFiles.setState({
      files: [
        {
          id: 'shared-document-id',
          filename: 'tenant-a.md',
          fileType: 'md',
          fileSize: 1,
          markdownContent: '',
          parsedAt: '2026-07-25T00:00:00.000Z',
          parser: 'test',
          status: 'pending',
        },
      ],
    })
    const pendingUpdate = useParsedFiles.getState().updateParsedFile('shared-document-id', {
      markdownContent: 'tenant-a-secret',
      status: 'parsed',
    })
    localStorage.setItem(
      'mimirq_parsed_files:tenant-b:user-b',
      makePersistedState('tenant-b.md', 'shared-document-id')
    )

    authMock.scope = 'tenant-b:user-b'
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    await vi.waitFor(() => {
      expect(useParsedFiles.getState().files[0]?.filename).toBe('tenant-b.md')
    })

    if (finishOldWrite) finishOldWrite()
    await pendingUpdate

    expect(useParsedFiles.getState().files[0]?.markdownContent).toBe('')
  })

  it('drops legacy unscoped state instead of exposing it in anonymous scope', async () => {
    localStorage.setItem('mimirq_parsed_files', makePersistedState('legacy-anon.md'))

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().files).toEqual([])
    expect(localStorage.getItem('mimirq_parsed_files')).toBeNull()
    expect(
      localStorage.getItem('mimirq_parsed_files:default:anonymous')?.includes('legacy-anon.md') ?? false
    ).toBe(false)
  })

  it('drops legacy unscoped state instead of exposing it in an authenticated scope', async () => {
    localStorage.setItem('mimirq_parsed_files', makePersistedState('legacy-private.md'))
    authMock.scope = 'tenant-a:user-a'

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().files).toEqual([])
    expect(localStorage.getItem('mimirq_parsed_files')).toBeNull()
    expect(
      localStorage.getItem('mimirq_parsed_files:tenant-a:user-a')?.includes('legacy-private.md') ?? false
    ).toBe(false)
  })

  it('removes the legacy unscoped key when scoped storage is cleared', () => {
    localStorage.setItem('mimirq_parsed_files', makePersistedState('legacy-private.md'))
    localStorage.setItem('mimirq_parsed_files:tenant-a:user-a', makePersistedState('tenant-a-file.md'))
    authMock.scope = 'tenant-a:user-a'

    useParsedFiles.persist.clearStorage()

    expect(localStorage.getItem('mimirq_parsed_files')).toBeNull()
    expect(localStorage.getItem('mimirq_parsed_files:tenant-a:user-a')).toBeNull()
  })

  it('freezes pending parsed-file updates to the original auth scope', async () => {
    authMock.scope = 'tenant-a:user-a'
    useParsedFiles.getState().addParsedFile({
      filename: 'scope-a.md',
      fileType: 'md',
      fileSize: 1,
      markdownContent: '# old',
      parser: 'unit-test',
    })
    const fileId = useParsedFiles.getState().files[0]?.id
    if (!fileId) throw new Error('expected file id to exist')

    let resolveSave: (() => void) | null = null
    vi.mocked(saveDocContentToCache).mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveSave = resolve
        })
    )

    const updatePromise = useParsedFiles.getState().updateParsedFile(fileId, {
      markdownContent: '# new',
      originalMarkdownContent: '# old',
      status: 'parsed',
    })

    expect(saveDocContentToCache).toHaveBeenCalledWith(
      expect.objectContaining({ id: fileId, markdownContent: '# new', originalMarkdownContent: '# old' }),
      'tenant-a:user-a'
    )

    authMock.scope = 'tenant-b:user-b'
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    ;(resolveSave as unknown as () => void)()
    await updatePromise

    expect(useParsedFiles.getState().files).toEqual([])
    expect(deleteDocContentFromCache).not.toHaveBeenCalled()
    expect(deleteDocSourceFromCache).not.toHaveBeenCalled()
  })

  it('keeps scoped persistence blocked until the latest rehydrate finishes', async () => {
    const pendingRehydrates: Array<() => void> = []
    const rehydrateSpy = vi.spyOn(useParsedFiles.persist, 'rehydrate').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          pendingRehydrates.push(resolve)
        })
    )

    try {
      authMock.scope = 'tenant-b:user-b'
      window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
      authMock.scope = 'tenant-c:user-c'
      window.dispatchEvent(new Event('mimirq:auth-scope-changed'))

      expect(rehydrateSpy).toHaveBeenCalledTimes(2)
      pendingRehydrates[0]?.()
      await Promise.resolve()
      await Promise.resolve()

      useParsedFiles.getState().addParsedFile({
        filename: 'must-not-persist-yet.md',
        fileType: 'md',
        fileSize: 1,
        markdownContent: '# pending',
        parser: 'unit-test',
      })
      expect(localStorage.getItem('mimirq_parsed_files:tenant-c:user-c')).toBeNull()

      pendingRehydrates[1]?.()
      await Promise.resolve()
      await Promise.resolve()
      useParsedFiles.getState().addParsedFile({
        filename: 'latest-scope.md',
        fileType: 'md',
        fileSize: 1,
        markdownContent: '# current',
        parser: 'unit-test',
      })
      expect(localStorage.getItem('mimirq_parsed_files:tenant-c:user-c')).toContain('latest-scope.md')
    } finally {
      for (const resolve of pendingRehydrates) resolve()
      rehydrateSpy.mockRestore()
    }
  })
})
