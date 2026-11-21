// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getAuthCacheScope } from '@/lib/auth-storage'
import { ROOT_FOLDER_ID, useParsedFiles } from './use-parsed-files-store'

vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))

const parsedFile = {
  id: 'document-a',
  filename: 'document.md',
  fileType: 'md',
  fileSize: 0,
  markdownContent: '',
  originalMarkdownContent: '',
  parsedAt: '2026-11-12T00:00:00Z',
  parser: 'test',
  folderId: ROOT_FOLDER_ID,
}

async function restoreParsedFiles(state: unknown, version = 0) {
  localStorage.setItem(`mimirq_parsed_files:${getAuthCacheScope()}`, JSON.stringify({ state, version }))
  await useParsedFiles.persist.rehydrate()
}

function rejectIndexWrites(message: string) {
  const storage = window.localStorage
  const error = new DOMException(message, 'QuotaExceededError')
  vi.spyOn(window, 'localStorage', 'get').mockReturnValue({
    get length() {
      return storage.length
    },
    key: storage.key.bind(storage),
    clear: storage.clear.bind(storage),
    getItem: storage.getItem.bind(storage),
    removeItem: storage.removeItem.bind(storage),
    setItem: () => {
      throw error
    },
  })
  return error
}

beforeEach(() => {
  useParsedFiles.setState(useParsedFiles.getInitialState(), true)
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  useParsedFiles.setState(useParsedFiles.getInitialState(), true)
  localStorage.clear()
})

describe('parsed file restoration', () => {
  it('uses a newly added empty preview without reading its cache again', async () => {
    const cache = await import('@/lib/doc-content-cache')
    vi.spyOn(cache, 'updateDocContentInCache').mockResolvedValue(undefined)
    const read = vi.spyOn(cache, 'getDocContentFromCache').mockRejectedValue(new Error('Cache read unavailable'))
    const id = await useParsedFiles.getState().addParsedFile({
      filename: 'empty.md',
      fileType: 'md',
      fileSize: 0,
      markdownContent: '',
      parser: 'text',
    })
    const file = useParsedFiles.getState().files.find((entry) => entry.id === id)
    if (file === undefined) throw new Error('Expected the newly added preview')
    const { loadParsingLibraryContent } = await import('@/components/parsing/parsing-library-content')
    await expect(loadParsingLibraryContent(file)).resolves.toMatchObject({
      content: { markdownContent: '', originalMarkdownContent: '' },
    })
    expect(read).not.toHaveBeenCalled()
  })

  it('keeps the accepted pending body when a replacement cannot write the index', async () => {
    const cache = await import('@/lib/doc-content-cache')
    let finishWrite!: () => void
    const write = vi
      .spyOn(cache, 'updateDocContentInCache')
      .mockReturnValueOnce(
        new Promise<void>((resolve) => {
          finishWrite = resolve
        }),
      )
      .mockResolvedValue(undefined)
    useParsedFiles.setState({ files: [parsedFile] })
    const accepted = useParsedFiles.getState().updateParsedFile(parsedFile.id, {
      markdownContent: 'Accepted pending body',
      status: 'parsed',
    })
    const failure = rejectIndexWrites('Replacement index write denied')
    await expect(
      useParsedFiles.getState().updateParsedFile(parsedFile.id, {
        markdownContent: 'Rejected replacement',
        status: 'error',
      }),
    ).rejects.toBe(failure)
    const acceptedWasAborted = write.mock.calls[0][2]?.aborted
    const writeCount = write.mock.calls.length
    vi.restoreAllMocks()
    finishWrite()
    await accepted
    expect(acceptedWasAborted).toBe(false)
    expect(writeCount).toBe(1)
    expect(useParsedFiles.getState().files[0].markdownContent).toBe('Accepted pending body')
  })

  it('rejects creating a child under a parent that no longer exists', () => {
    expect(() => useParsedFiles.getState().createFolder('Child', 'missing-parent')).toThrow('父文件夹')
    expect(useParsedFiles.getState().folders).toEqual([])
  })

  it.each(['create', 'rename', 'move', 'delete'] as const)(
    'retains folder data and location when %s cannot write the index',
    (operation) => {
      const parentId = useParsedFiles.getState().createFolder('Parent')
      const folderId = useParsedFiles.getState().createFolder('Subject')
      useParsedFiles.getState().upsertParsedFile({ ...parsedFile, folderId })
      useParsedFiles.getState().setActiveFolderId(folderId)
      const before = useParsedFiles.getState()
      const key = `mimirq_parsed_files:${getAuthCacheScope()}`
      const raw = localStorage.getItem(key)
      const failure = rejectIndexWrites('Folder index write denied')
      const action = () => {
        const state = useParsedFiles.getState()
        if (operation === 'create') state.createFolder('New child', folderId)
        else if (operation === 'rename') state.renameFolder(folderId, 'Renamed')
        else if (operation === 'move') state.moveFolder(folderId, parentId)
        else state.deleteFolder(folderId)
      }
      expect(action).toThrow(failure)
      expect(useParsedFiles.getState().folders).toEqual(before.folders)
      expect(useParsedFiles.getState().files).toEqual(before.files)
      expect(useParsedFiles.getState().activeFolderId).toBe(folderId)
      expect(localStorage.getItem(key)).toBe(raw)
    },
  )

  it.each([
    [{ id: 'self', name: 'Self', parentId: 'self', createdAt: '' }],
    [
      { id: 'cycle-a', name: 'A', parentId: 'cycle-b', createdAt: '' },
      { id: 'cycle-b', name: 'B', parentId: 'cycle-a', createdAt: '' },
    ],
  ])('rejects a cyclic stored folder hierarchy without rewriting its raw index: %j', async (...folders) => {
    useParsedFiles.setState({ files: [parsedFile] })
    const raw = JSON.stringify({ state: { files: [], folders }, version: 0 })
    const key = `mimirq_parsed_files:${getAuthCacheScope()}`
    localStorage.setItem(key, raw)
    await useParsedFiles.persist.rehydrate()
    expect(useParsedFiles.getState().loadError).toBeInstanceOf(Error)
    expect(String(useParsedFiles.getState().loadError)).toContain('循环')
    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(localStorage.getItem(key)).toBe(raw)
  })

  it.each([
    [{ id: 'orphan', name: 'Orphan', parentId: 'missing', createdAt: '' }],
    [
      { id: 'duplicate', name: 'First', parentId: 'root', createdAt: '' },
      { id: 'duplicate', name: 'Second', parentId: 'root', createdAt: '' },
    ],
  ])('rejects a stored folder graph with missing or repeated identities: %j', async (...folders) => {
    await restoreParsedFiles({ files: [parsedFile], folders })
    expect(useParsedFiles.getState().loadError).toBeInstanceOf(Error)
    expect(useParsedFiles.getState().isLoaded).toBe(false)
  })

  it('retains the ready record when an awaited handoff cannot write its index', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const restoreContent = vi.fn().mockResolvedValue(undefined)
    vi.spyOn(cache, 'updateDocContentInCache').mockResolvedValue(restoreContent)
    const original = {
      ...parsedFile,
      markdownContent: 'Keep body',
      originalMarkdownContent: 'Keep original',
      governanceStatus: 'ready' as const,
    }
    useParsedFiles.setState({ files: [original] })
    const storage = window.localStorage
    const failure = new DOMException('Index write denied', 'QuotaExceededError')
    vi.spyOn(window, 'localStorage', 'get').mockReturnValue({
      get length() {
        return storage.length
      },
      key: storage.key.bind(storage),
      clear: storage.clear.bind(storage),
      getItem: storage.getItem.bind(storage),
      removeItem: storage.removeItem.bind(storage),
      setItem: () => {
        throw failure
      },
    })
    await expect(
      useParsedFiles.getState().updateParsedFile(original.id, {
        markdownContent: 'Transferred body',
        originalMarkdownContent: 'Transferred original',
        governanceStatus: 'submitted',
        status: 'parsed',
      }),
    ).rejects.toBe(failure)
    expect(restoreContent).toHaveBeenCalledOnce()
    expect(useParsedFiles.getState().files).toEqual([original])
  })

  it('replaces a local preview once and retains its current folder and workflow metadata', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const write = vi.spyOn(cache, 'updateDocContentInCache').mockResolvedValue(undefined)
    const deleteContent = vi.spyOn(cache, 'deleteDocContentFromCache').mockResolvedValue(undefined)
    const deleteSource = vi.spyOn(cache, 'deleteDocSourceFromCache').mockResolvedValue(undefined)
    const original = {
      ...parsedFile,
      folderId: 'moved-folder',
      datasetId: 'dataset-a',
      governanceStatus: 'ready' as const,
    }
    const parsed = {
      ...parsedFile,
      id: 'server-a',
      source: 'parsing_workspace' as const,
      markdownContent: 'Parsed',
      originalMarkdownContent: 'Raw',
    }
    useParsedFiles.setState({ files: [original, { ...parsed, markdownContent: '' }] })

    useParsedFiles.getState().replaceParsedFile(original.id, parsed)

    expect(useParsedFiles.getState().files).toEqual([{ ...original, ...parsed, folderId: 'moved-folder' }])
    await vi.waitFor(() =>
      expect(write).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'server-a', markdownContent: 'Parsed', originalMarkdownContent: 'Raw' }),
        getAuthCacheScope(),
        expect.any(AbortSignal),
      ),
    )
    expect(deleteContent).toHaveBeenCalledWith(original.id, getAuthCacheScope())
    expect(deleteSource).toHaveBeenCalledWith(original.id, getAuthCacheScope())
    const snapshot = JSON.parse(localStorage.getItem(`mimirq_parsed_files:${getAuthCacheScope()}`)!) as {
      state: { files: Array<{ id: string }> }
    }
    expect(snapshot.state.files.map((file) => file.id)).toEqual(['server-a'])
  })

  it('preserves the original preview if its replacement index cannot be written', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const write = vi.spyOn(cache, 'updateDocContentInCache')
    const cleanup = vi.spyOn(cache, 'deleteDocContentFromCache')
    useParsedFiles.setState({ files: [parsedFile] })
    const failure = new DOMException('Index quota exceeded', 'QuotaExceededError')
    const storage = window.localStorage
    vi.spyOn(window, 'localStorage', 'get').mockReturnValue({
      get length() {
        return storage.length
      },
      key: storage.key.bind(storage),
      clear: storage.clear.bind(storage),
      getItem: storage.getItem.bind(storage),
      removeItem: storage.removeItem.bind(storage),
      setItem: () => {
        throw failure
      },
    })

    expect(() => useParsedFiles.getState().replaceParsedFile(parsedFile.id, { ...parsedFile, id: 'server-a' })).toThrow(
      failure,
    )

    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(write).not.toHaveBeenCalled()
    expect(cleanup).not.toHaveBeenCalled()
  })

  it('does not recreate a local preview deleted before parsing finished', () => {
    expect(() =>
      useParsedFiles.getState().replaceParsedFile('deleted-preview', { ...parsedFile, id: 'server-a' }),
    ).toThrow('已移除')
    expect(useParsedFiles.getState().files).toEqual([])
  })

  it('preserves a known read failure when a retry cannot access browser storage', async () => {
    useParsedFiles.setState({ files: [parsedFile] })
    const key = `mimirq_parsed_files:${getAuthCacheScope()}`
    const raw = JSON.stringify({ state: { files: null }, version: 0 })
    localStorage.setItem(key, raw)
    await useParsedFiles.persist.rehydrate()
    const readError = useParsedFiles.getState().loadError
    expect(readError).toBeInstanceOf(Error)
    const storageAccess = vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('Browser storage is unavailable', 'SecurityError')
    })

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().loadError).toBe(readError)
    expect(useParsedFiles.getState().isLoaded).toBe(false)
    storageAccess.mockRestore()
    useParsedFiles.getState().setActiveFolderId('temporary-folder')
    expect(localStorage.getItem(key)).toBe(raw)
    await restoreParsedFiles({ files: [parsedFile] })
    expect(useParsedFiles.getState().isLoaded).toBe(true)
    expect(useParsedFiles.getState().loadError).toBeUndefined()
  })

  it.each([null, 42, {}, [], { state: { files: [] }, version: 'invalid' }])(
    'retains the raw value when the stored wrapper is invalid: %j',
    async (snapshot) => {
      useParsedFiles.setState({ files: [parsedFile] })
      const key = `mimirq_parsed_files:${getAuthCacheScope()}`
      const raw = JSON.stringify(snapshot)
      localStorage.setItem(key, raw)

      await useParsedFiles.persist.rehydrate()

      expect(useParsedFiles.getState().files).toEqual([parsedFile])
      expect(useParsedFiles.getState().isLoaded).toBe(false)
      expect(useParsedFiles.getState().loadError).toBeInstanceOf(Error)
      expect(localStorage.getItem(key)).toBe(raw)
    },
  )

  it('retains the supported object wrapper without a version field', async () => {
    localStorage.setItem(
      `mimirq_parsed_files:${getAuthCacheScope()}`,
      JSON.stringify({ state: { files: [parsedFile] } }),
    )

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(useParsedFiles.getState().isLoaded).toBe(true)
  })

  it.each([42, {}, { files: null }, { files: [], folders: 42 }])(
    'retains the raw index and current files when collection structure is invalid: %j',
    async (state) => {
      useParsedFiles.setState({ files: [parsedFile] })

      await restoreParsedFiles(state)

      expect(useParsedFiles.getState().files).toEqual([parsedFile])
      expect(useParsedFiles.getState().isLoaded).toBe(false)
      expect(useParsedFiles.getState().loadError).toBeInstanceOf(Error)
      expect(localStorage.getItem(`mimirq_parsed_files:${getAuthCacheScope()}`)).toBe(
        JSON.stringify({ state, version: 0 }),
      )
    },
  )

  it.each([0, -1])('retains the supported files-only object snapshot at version %s', async (version) => {
    await restoreParsedFiles({ files: [parsedFile] }, version)

    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(useParsedFiles.getState().folders).toEqual([])
    expect(useParsedFiles.getState().activeFolderId).toBe(ROOT_FOLDER_ID)
    expect(useParsedFiles.getState().isLoaded).toBe(true)
  })

  it('reports a failed background content write while retaining the accepted memory edit', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const failure = new Error('Background content write failed')
    vi.spyOn(cache, 'updateDocContentInCache').mockRejectedValue(failure)
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    useParsedFiles.setState({ files: [parsedFile] })

    await useParsedFiles.getState().updateParsedFile(parsedFile.id, { markdownContent: 'Accepted working edit' })

    await vi.waitFor(() => expect(warning).toHaveBeenCalledWith(expect.any(String), failure))
    expect(useParsedFiles.getState().files[0].markdownContent).toBe('Accepted working edit')
  })

  it('reports cache cleanup failure after removing the library entry and attempts both cache stores', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const failure = new Error('Cache cleanup failed')
    vi.spyOn(cache, 'deleteDocContentFromCache').mockRejectedValue(failure)
    const deleteSource = vi.spyOn(cache, 'deleteDocSourceFromCache').mockResolvedValue(undefined)
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    useParsedFiles.setState({ files: [parsedFile] })

    useParsedFiles.getState().removeFile(parsedFile.id)

    await vi.waitFor(() => expect(warning).toHaveBeenCalledWith(expect.any(String), failure))
    expect(useParsedFiles.getState().files).toEqual([])
    expect(deleteSource).toHaveBeenCalledWith(parsedFile.id, getAuthCacheScope())
  })

  it('keeps memory edits available but rejects an explicit save without local storage', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const write = vi.spyOn(cache, 'updateDocContentInCache').mockResolvedValue(undefined)
    useParsedFiles.setState({ files: [parsedFile] })
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('Browser storage is unavailable', 'SecurityError')
    })
    await useParsedFiles.persist.rehydrate()
    await useParsedFiles.getState().updateParsedFile(parsedFile.id, { parser: 'in-memory' })

    await expect(
      useParsedFiles
        .getState()
        .updateParsedFile(parsedFile.id, { markdownContent: 'Not saved' }, { requirePersistence: true }),
    ).rejects.toThrow('无法保存')

    expect(useParsedFiles.getState().files[0]).toMatchObject({ parser: 'in-memory', markdownContent: '' })
    expect(write).not.toHaveBeenCalled()
  })

  it('rejects saving if local storage becomes unavailable while content is being written', async () => {
    const cache = await import('@/lib/doc-content-cache')
    let finishWrite!: () => void
    vi.spyOn(cache, 'updateDocContentInCache').mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishWrite = resolve
      }),
    )
    useParsedFiles.setState({ files: [parsedFile] })
    const pending = useParsedFiles
      .getState()
      .updateParsedFile(parsedFile.id, { markdownContent: 'Not saved' }, { requirePersistence: true })
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('Browser storage is unavailable', 'SecurityError')
    })

    finishWrite()

    await expect(pending).rejects.toThrow('无法保存')
    expect(useParsedFiles.getState().files[0].markdownContent).toBe('')
  })

  it('rejects an explicit save when catalog replacement removed its target during the content write', async () => {
    const cache = await import('@/lib/doc-content-cache')
    let finishWrite!: () => void
    vi.spyOn(cache, 'updateDocContentInCache').mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishWrite = resolve
      }),
    )
    useParsedFiles.setState({ files: [parsedFile] })
    const pending = useParsedFiles
      .getState()
      .updateParsedFile(parsedFile.id, { markdownContent: 'Not saved' }, { requirePersistence: true })
    useParsedFiles.getState().setParsedFiles([])

    finishWrite()

    await expect(pending).rejects.toThrow('文档已移除')
    expect(useParsedFiles.getState().files).toEqual([])
  })

  it('reports explicit save cancellation instead of resolving as if it completed', async () => {
    const cache = await import('@/lib/doc-content-cache')
    let finishWrite!: () => void
    vi.spyOn(cache, 'updateDocContentInCache').mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishWrite = resolve
      }),
    )
    vi.spyOn(cache, 'deleteDocContentFromCache').mockResolvedValue(undefined)
    vi.spyOn(cache, 'deleteDocSourceFromCache').mockResolvedValue(undefined)
    useParsedFiles.setState({ files: [parsedFile] })
    const pending = useParsedFiles
      .getState()
      .updateParsedFile(parsedFile.id, { markdownContent: 'Not saved' }, { requirePersistence: true })
    useParsedFiles.getState().removeFile(parsedFile.id)

    finishWrite()

    await expect(pending).rejects.toHaveProperty('name', 'AbortError')
    expect(useParsedFiles.getState().files).toEqual([])
  })

  it('retains optional memory completion but exposes the same cache failure for explicit saving', async () => {
    const cache = await import('@/lib/doc-content-cache')
    const failure = new Error('Content store unavailable')
    const write = vi.spyOn(cache, 'updateDocContentInCache').mockRejectedValue(failure)
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    useParsedFiles.setState({ files: [parsedFile] })

    await useParsedFiles
      .getState()
      .updateParsedFile(parsedFile.id, { markdownContent: 'In-memory content', status: 'parsed' })
    await expect(
      useParsedFiles
        .getState()
        .updateParsedFile(
          parsedFile.id,
          { markdownContent: 'Not saved', status: 'parsed' },
          { requirePersistence: true },
        ),
    ).rejects.toBe(failure)

    expect(useParsedFiles.getState().files[0].markdownContent).toBe('In-memory content')
    expect(warning).toHaveBeenCalledOnce()
    expect(write).toHaveBeenCalledTimes(2)
  })

  it('retains current content if restoration fails while an awaited content write is pending', async () => {
    const cache = await import('@/lib/doc-content-cache')
    let finishWrite!: () => void
    vi.spyOn(cache, 'updateDocContentInCache').mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishWrite = resolve
      }),
    )
    useParsedFiles.setState({ files: [parsedFile] })
    const pending = useParsedFiles
      .getState()
      .updateParsedFile(parsedFile.id, { markdownContent: 'Uncommitted content', status: 'parsed' })
    const key = `mimirq_parsed_files:${getAuthCacheScope()}`
    const malformed = '{invalid document index during content write'
    localStorage.setItem(key, malformed)
    await useParsedFiles.persist.rehydrate()
    const readError = useParsedFiles.getState().loadError

    finishWrite()

    await expect(pending).rejects.toBe(readError)
    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(localStorage.getItem(key)).toBe(malformed)
  })

  it.each(['removeFile', 'deleteFolder', 'clearAll'] as const)(
    'rejects %s before changing current data when the index could not be read',
    async (action) => {
      const file = { ...parsedFile, folderId: 'folder-a' }
      const folder = { id: 'folder-a', name: 'Folder A', parentId: ROOT_FOLDER_ID, createdAt: '2026-11-12' }
      useParsedFiles.setState({ files: [file], folders: [folder] })
      const key = `mimirq_parsed_files:${getAuthCacheScope()}`
      const malformed = '{invalid document index before delete'
      localStorage.setItem(key, malformed)
      await useParsedFiles.persist.rehydrate()

      expect(() => {
        if (action === 'removeFile') useParsedFiles.getState().removeFile(file.id)
        else if (action === 'deleteFolder') useParsedFiles.getState().deleteFolder(folder.id)
        else useParsedFiles.getState().clearAll()
      }).toThrow(SyntaxError)

      expect(useParsedFiles.getState().files).toEqual([file])
      expect(useParsedFiles.getState().folders).toEqual([folder])
      expect(localStorage.getItem(key)).toBe(malformed)
    },
  )

  it('keeps directory browsing transient after a read failure and rejects real metadata writes', async () => {
    useParsedFiles.setState({ files: [parsedFile] })
    const key = `mimirq_parsed_files:${getAuthCacheScope()}`
    const malformed = '{invalid protected document index'
    localStorage.setItem(key, malformed)
    await useParsedFiles.persist.rehydrate()
    const readError = useParsedFiles.getState().loadError

    useParsedFiles.getState().setActiveFolderId('temporary-folder')
    expect(useParsedFiles.getState().activeFolderId).toBe('temporary-folder')
    expect(localStorage.getItem(key)).toBe(malformed)

    await expect(useParsedFiles.getState().updateParsedFile(parsedFile.id, { parser: 'updated' })).rejects.toBe(
      readError,
    )
    expect(localStorage.getItem(key)).toBe(malformed)
  })

  it('retains current memory files when there is no stored snapshot', async () => {
    useParsedFiles.setState({ files: [parsedFile] })
    localStorage.removeItem(`mimirq_parsed_files:${getAuthCacheScope()}`)

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(useParsedFiles.getState().isLoaded).toBe(true)
    expect(useParsedFiles.getState().loadError).toBeUndefined()
  })

  it('keeps an initial malformed-cache error observable after Store creation', async () => {
    const key = `mimirq_parsed_files:${getAuthCacheScope()}`
    const malformed = '{invalid initial document index'
    localStorage.setItem(key, malformed)
    vi.resetModules()

    const { useParsedFiles: reloadedStore } = await import('./use-parsed-files-store')

    await vi.waitFor(() => expect(reloadedStore.getState().loadError).toBeInstanceOf(SyntaxError))
    expect(reloadedStore.getState().isLoaded).toBe(false)
    expect(localStorage.getItem(key)).toBe(malformed)
  })

  it.each([0, -1])('reports malformed JSON and recovers through a valid version %s retry', async (version) => {
    useParsedFiles.setState({ files: [parsedFile], isLoaded: true })
    const key = `mimirq_parsed_files:${getAuthCacheScope()}`
    const malformed = '{invalid cached document index'
    localStorage.setItem(key, malformed)

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().loadError).toBeInstanceOf(SyntaxError)
    expect(useParsedFiles.getState().isLoaded).toBe(false)
    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(localStorage.getItem(key)).toBe(malformed)

    await restoreParsedFiles({ files: [parsedFile], folders: [], activeFolderId: ROOT_FOLDER_ID }, version)

    expect(useParsedFiles.getState().loadError).toBeUndefined()
    expect(useParsedFiles.getState().isLoaded).toBe(true)
    expect(useParsedFiles.getState().files).toEqual([parsedFile])
  })

  it('reports storage read failures without writing a replacement snapshot', async () => {
    useParsedFiles.setState({ files: [parsedFile] })
    const storage = window.localStorage
    const readError = new DOMException('Document storage access denied', 'SecurityError')
    const write = vi.fn(storage.setItem.bind(storage))
    vi.spyOn(window, 'localStorage', 'get').mockReturnValue({
      get length() {
        return storage.length
      },
      key: storage.key.bind(storage),
      clear: storage.clear.bind(storage),
      getItem: () => {
        throw readError
      },
      removeItem: storage.removeItem.bind(storage),
      setItem: write,
    })

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().loadError).toBe(readError)
    expect(useParsedFiles.getState().isLoaded).toBe(false)
    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(write).not.toHaveBeenCalled()
  })

  it('keeps current files in the supported mode without browser storage', async () => {
    useParsedFiles.setState({ files: [parsedFile] })
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('Browser storage is unavailable', 'SecurityError')
    })

    await useParsedFiles.persist.rehydrate()

    expect(useParsedFiles.getState().files).toEqual([parsedFile])
    expect(useParsedFiles.getState().isLoaded).toBe(true)
    expect(useParsedFiles.getState().loadError).toBeUndefined()
  })

  it('restores current-version data while retaining the real actions', async () => {
    await restoreParsedFiles({
      files: [parsedFile],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
      getFile: 'stored data',
      unrelated: 'not library state',
    })

    expect(useParsedFiles.getState().getFile).toBeTypeOf('function')
    expect(useParsedFiles.getState().getFile(parsedFile.id)).toMatchObject(parsedFile)
    expect(useParsedFiles.getState()).not.toHaveProperty('unrelated')
    expect(useParsedFiles.getState().isLoaded).toBe(true)
  })

  it('restores a real empty current-version snapshot without inventing file entries', async () => {
    useParsedFiles.setState({ files: [parsedFile] })
    await restoreParsedFiles({ files: [], folders: [], activeFolderId: ROOT_FOLDER_ID })

    expect(useParsedFiles.getState().files).toEqual([])
    expect(useParsedFiles.getState().folders).toEqual([])
    expect(useParsedFiles.getState().activeFolderId).toBe(ROOT_FOLDER_ID)
    expect(useParsedFiles.getState().isLoaded).toBe(true)
  })

  it('keeps the supported older array format without importing action fields', async () => {
    await restoreParsedFiles([parsedFile], -1)

    expect(useParsedFiles.getState().getFile(parsedFile.id)).toMatchObject(parsedFile)
    expect(useParsedFiles.getState().folders).toEqual([])
    expect(useParsedFiles.getState().activeFolderId).toBe(ROOT_FOLDER_ID)
  })

  it('preserves supplied metadata when setting and upserting known parsed files', () => {
    const file = { ...parsedFile, parsedAt: '' }
    useParsedFiles.getState().setParsedFiles([file])
    expect(useParsedFiles.getState().getFile(file.id)).toMatchObject({ id: file.id, parsedAt: '', fileSize: 0 })

    useParsedFiles.getState().upsertParsedFile({ ...file, filename: 'updated.md' })
    expect(useParsedFiles.getState().getFile(file.id)).toMatchObject({
      filename: 'updated.md',
      parsedAt: '',
      fileSize: 0,
    })
  })

  it('keeps valid records alongside malformed current-version file metadata', async () => {
    await restoreParsedFiles({
      files: [
        {},
        { ...parsedFile, id: 42 },
        { ...parsedFile, filename: null },
        { ...parsedFile, fileSize: 'large' },
        { ...parsedFile, governanceReview: { issues: 'not a list' } },
        { ...parsedFile, elements: [{ id: 42, kind: 'paragraph' }] },
        { ...parsedFile, parsedAt: '' },
      ],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
    })

    expect(useParsedFiles.getState().files).toHaveLength(1)
    expect(useParsedFiles.getState().files[0]).toMatchObject({ id: parsedFile.id, parsedAt: '', fileSize: 0 })
    expect(() => useParsedFiles.getState().files.map((file) => file.filename.toLowerCase())).not.toThrow()
  })

  it('retains valid optional parsing and governance data', async () => {
    const file = {
      ...parsedFile,
      datasetId: null,
      durationSec: 0,
      elements: [
        { id: 'element-a', kind: 'paragraph', page: 0, confidence: 0, text: '', attributes: { source: 'test' } },
      ],
      governanceReview: {
        qualityScore: 0,
        issues: [{ id: 'issue-a', type: 'warning', message: '', position: { start: 0, end: 1 } }],
        annotations: [{ id: 'annotation-a', type: 'entity', text: '', label: '', start: 0, end: 1 }],
        tags: [],
        category: null,
      },
    }
    await restoreParsedFiles({ files: [file], folders: [], activeFolderId: ROOT_FOLDER_ID })

    expect(useParsedFiles.getState().getFile(file.id)).toMatchObject(file)
  })

  it('keeps supplied folder timestamps and ignores records without a stored timestamp', async () => {
    const folder = { id: 'folder-a', name: 'Folder', parentId: ROOT_FOLDER_ID, createdAt: '' }
    await restoreParsedFiles({
      files: [],
      folders: [{ id: 'missing-date', name: 'Invalid', parentId: ROOT_FOLDER_ID }, folder],
      activeFolderId: ROOT_FOLDER_ID,
    })

    expect(useParsedFiles.getState().folders).toEqual([folder])
  })

  it('does not keep a selection pointing at a missing restored folder', async () => {
    await restoreParsedFiles({ files: [parsedFile], folders: [], activeFolderId: 'missing-folder' })

    expect(useParsedFiles.getState().activeFolderId).toBe(ROOT_FOLDER_ID)
    expect(useParsedFiles.getState().getFile(parsedFile.id)).toMatchObject(parsedFile)
  })

  it.each(['source', 'missing'])(
    'rejects the requested invalid folder target without moving to root: %s',
    async (target) => {
      await restoreParsedFiles({
        files: [],
        folders: [
          { id: 'parent', name: 'Parent', parentId: ROOT_FOLDER_ID, createdAt: '' },
          { id: 'source', name: 'Source', parentId: 'parent', createdAt: '' },
        ],
        activeFolderId: ROOT_FOLDER_ID,
      })

      expect(useParsedFiles.getState().moveFolder('source', target)).toBe(false)
      expect(useParsedFiles.getState().folders.find((folder) => folder.id === 'source')?.parentId).toBe('parent')
    },
  )

  it('moves to an existing target or root and rejects descendant targets', async () => {
    await restoreParsedFiles({
      files: [],
      folders: [
        { id: 'parent', name: 'Parent', parentId: ROOT_FOLDER_ID, createdAt: '' },
        { id: 'source', name: 'Source', parentId: 'parent', createdAt: '' },
        { id: 'child', name: 'Child', parentId: 'source', createdAt: '' },
        { id: 'target', name: 'Target', parentId: ROOT_FOLDER_ID, createdAt: '' },
      ],
      activeFolderId: ROOT_FOLDER_ID,
    })

    expect(useParsedFiles.getState().moveFolder('source', 'child')).toBe(false)
    expect(useParsedFiles.getState().moveFolder('source', 'target')).toBe(true)
    expect(useParsedFiles.getState().folders.find((folder) => folder.id === 'source')?.parentId).toBe('target')
    expect(useParsedFiles.getState().moveFolder('source', ROOT_FOLDER_ID)).toBe(true)
    expect(useParsedFiles.getState().folders.find((folder) => folder.id === 'source')?.parentId).toBe(ROOT_FOLDER_ID)
  })

  it('terminates a move if the current target chain was corrupted into a cycle', () => {
    useParsedFiles.setState({
      folders: [
        { id: 'source', name: 'Source', parentId: ROOT_FOLDER_ID, createdAt: '' },
        { id: 'cycle-a', name: 'Cycle A', parentId: 'cycle-b', createdAt: '' },
        { id: 'cycle-b', name: 'Cycle B', parentId: 'cycle-a', createdAt: '' },
      ],
    })
    expect(useParsedFiles.getState().moveFolder('source', 'cycle-a')).toBe(false)
    expect(useParsedFiles.getState().folders[0].parentId).toBe(ROOT_FOLDER_ID)
  })
})
